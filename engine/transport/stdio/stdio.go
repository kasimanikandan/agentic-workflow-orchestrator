// Package stdio implements the embedded transport: newline-delimited JSON (NDJSON)
// over stdin/stdout.
//
// Protocol (each message is one JSON object on one line):
//
//	Client → Engine:
//	  {"type":"start_run","spec_json":"...","inputs_json":"..."}
//	  {"type":"skill_result","invocation_id":"...","output_json":"...",
//	   "error":{"type":"...","message":"...","retryable":false}|null,
//	   "decisions":[...],"llm_usage":{...}|null,"tool_calls":0}
//	  {"type":"cancel_run","run_id":"..."}
//
//	Engine → Client:
//	  {"type":"run_accepted","run_id":"..."}
//	  {"type":"skill_invocation","invocation_id":"...","run_id":"...","task_id":"...","skill":"...","inputs_json":"...","attempt":1}
//	  {"type":"event","run_id":"...","task_id":"...","event_type":"task.started","at_unix_ms":...}
//	  {"type":"report",...}   (final; engine then exits cleanly)
//
// Multiple skill_invocation messages may be in-flight concurrently. Each
// skill_result is correlated by invocation_id.
package stdio

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sync"

	"github.com/org/orchestrator/internal/scheduler"
)

// ---------------------------------------------------------------------------
// Wire types
// ---------------------------------------------------------------------------

type inMsg struct {
	Type string `json:"type"`
	// start_run
	SpecJSON   string `json:"spec_json,omitempty"`
	InputsJSON string `json:"inputs_json,omitempty"`
	// skill_result
	InvocationID string          `json:"invocation_id,omitempty"`
	OutputJSON   string          `json:"output_json,omitempty"`
	Error        *wireSkillError `json:"error,omitempty"`
	Decisions    []wireDecision  `json:"decisions,omitempty"`
	LLMUsage     *wireLLMUsage   `json:"llm_usage,omitempty"`
	ToolCalls    int64           `json:"tool_calls,omitempty"`
	// cancel_run
	RunID string `json:"run_id,omitempty"`
}

type wireSkillError struct {
	Type      string `json:"type"`
	Message   string `json:"message"`
	Retryable bool   `json:"retryable"`
}

type wireDecision struct {
	AtMs      int64  `json:"at_ms"`
	Summary   string `json:"summary"`
	Rationale string `json:"rationale,omitempty"`
	DataJSON  string `json:"data_json,omitempty"`
}

type wireLLMUsage struct {
	Provider  string `json:"provider"`
	Model     string `json:"model"`
	TokensIn  int64  `json:"tokens_in"`
	TokensOut int64  `json:"tokens_out"`
}

type outMsg struct {
	Type string `json:"type"`
	// run_accepted
	RunID string `json:"run_id,omitempty"`
	// skill_invocation
	InvocationID string `json:"invocation_id,omitempty"`
	TaskID       string `json:"task_id,omitempty"`
	Skill        string `json:"skill,omitempty"`
	InputsJSON   string `json:"inputs_json,omitempty"`
	Attempt      int    `json:"attempt,omitempty"`
	// event
	EventType string `json:"event_type,omitempty"`
	AtUnixMs  int64  `json:"at_unix_ms,omitempty"`
	// report (embedded as raw JSON to avoid double-encoding)
	Report json.RawMessage `json:"report,omitempty"`
}

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

// Transport is the stdio Executor and message pump.
type Transport struct {
	in      io.Reader
	out     io.Writer
	outMu   sync.Mutex
	pending map[string]chan scheduler.Result // invocation_id → result channel
	pendMu  sync.Mutex
}

// NewTransport creates a transport reading from in and writing to out.
// Use os.Stdin / os.Stdout for the embedded binary case.
func NewTransport(in io.Reader, out io.Writer) *Transport {
	return &Transport{
		in:      in,
		out:     out,
		pending: make(map[string]chan scheduler.Result),
	}
}

// ReadStartRun reads the initial start_run message from stdin.
func (t *Transport) ReadStartRun() (specJSON, inputsJSON string, err error) {
	var msg inMsg
	if err = t.readOne(&msg); err != nil {
		return "", "", fmt.Errorf("stdio: reading start_run: %w", err)
	}
	if msg.Type != "start_run" {
		return "", "", fmt.Errorf("stdio: expected start_run, got %q", msg.Type)
	}
	return msg.SpecJSON, msg.InputsJSON, nil
}

// SendRunAccepted tells the client the run was accepted.
func (t *Transport) SendRunAccepted(runID string) error {
	return t.writeOne(outMsg{Type: "run_accepted", RunID: runID})
}

// SendEvent forwards a scheduler event to the client.
func (t *Transport) SendEvent(e scheduler.Event) error {
	return t.writeOne(outMsg{
		Type:      "event",
		RunID:     e.RunID,
		TaskID:    e.TaskID,
		EventType: string(e.Type),
		AtUnixMs:  e.AtUnixMs,
	})
}

// SendReport sends the final report and flushes.
func (t *Transport) SendReport(rep any) error {
	b, err := json.Marshal(rep)
	if err != nil {
		return err
	}
	return t.writeOne(outMsg{Type: "report", Report: json.RawMessage(b)})
}

// PumpIncoming reads skill_result and cancel_run messages from stdin, dispatching
// results to waiting Execute() calls. Must be called in its own goroutine.
// Returns when ctx is cancelled or stdin is closed.
func (t *Transport) PumpIncoming(ctx context.Context, cancelRun context.CancelFunc) {
	scanner := bufio.NewScanner(t.in)
	scanner.Buffer(make([]byte, 4*1024*1024), 4*1024*1024) // 4 MB per line
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}
		var msg inMsg
		if err := json.Unmarshal(line, &msg); err != nil {
			continue
		}
		switch msg.Type {
		case "skill_result":
			t.pendMu.Lock()
			ch, ok := t.pending[msg.InvocationID]
			t.pendMu.Unlock()
			if !ok {
				continue
			}
			res := scheduler.Result{
				InvocationID: msg.InvocationID,
				OutputJSON:   msg.OutputJSON,
				ToolCalls:    msg.ToolCalls,
			}
			if msg.Error != nil {
				res.Err = &scheduler.SkillError{
					Type:      msg.Error.Type,
					Message:   msg.Error.Message,
					Retryable: msg.Error.Retryable,
				}
			}
			for _, d := range msg.Decisions {
				res.Decisions = append(res.Decisions, scheduler.Decision{
					AtMs:      d.AtMs,
					Summary:   d.Summary,
					Rationale: d.Rationale,
					DataJSON:  d.DataJSON,
				})
			}
			if msg.LLMUsage != nil {
				res.LLMUsage = &scheduler.LLMUsage{
					Provider:  msg.LLMUsage.Provider,
					Model:     msg.LLMUsage.Model,
					TokensIn:  msg.LLMUsage.TokensIn,
					TokensOut: msg.LLMUsage.TokensOut,
				}
			}
			ch <- res
		case "cancel_run":
			cancelRun()
		}
		select {
		case <-ctx.Done():
			return
		default:
		}
	}
}

// Execute implements scheduler.Executor.
// It sends a skill_invocation to stdout and blocks until the matching
// skill_result arrives on stdin (via PumpIncoming).
func (t *Transport) Execute(ctx context.Context, inv scheduler.Invocation) (scheduler.Result, error) {
	ch := make(chan scheduler.Result, 1)
	t.pendMu.Lock()
	t.pending[inv.InvocationID] = ch
	t.pendMu.Unlock()
	defer func() {
		t.pendMu.Lock()
		delete(t.pending, inv.InvocationID)
		t.pendMu.Unlock()
	}()

	if err := t.writeOne(outMsg{
		Type:         "skill_invocation",
		InvocationID: inv.InvocationID,
		RunID:        inv.RunID,
		TaskID:       inv.TaskID,
		Skill:        inv.Skill,
		InputsJSON:   inv.InputsJSON,
		Attempt:      inv.Attempt,
	}); err != nil {
		return scheduler.Result{}, fmt.Errorf("stdio: sending skill_invocation: %w", err)
	}

	select {
	case <-ctx.Done():
		return scheduler.Result{}, ctx.Err()
	case res := <-ch:
		return res, nil
	}
}

// ---------------------------------------------------------------------------
// Low-level read/write helpers
// ---------------------------------------------------------------------------

func (t *Transport) readOne(v any) error {
	scanner := bufio.NewScanner(t.in)
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}
		return json.Unmarshal(line, v)
	}
	if err := scanner.Err(); err != nil {
		return err
	}
	return io.EOF
}

func (t *Transport) writeOne(v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	t.outMu.Lock()
	defer t.outMu.Unlock()
	_, err = fmt.Fprintf(t.out, "%s\n", b)
	return err
}

// ---------------------------------------------------------------------------
// Convenience: Run wires everything together for the embedded binary case.
// ---------------------------------------------------------------------------

// Run reads a start_run from stdin, executes the workflow, writes events +
// the final report to stdout. Blocks until the run finishes.
func Run(ctx context.Context, runFn func(ctx context.Context, specJSON, inputsJSON string, tr *Transport) error) error {
	tr := NewTransport(os.Stdin, os.Stdout)
	specJSON, inputsJSON, err := tr.ReadStartRun()
	if err != nil {
		return err
	}
	return runFn(ctx, specJSON, inputsJSON, tr)
}
