// Package scheduler is the orchestration engine core.
//
// It walks the workflow DAG, dispatching every "ready" task (all deps satisfied)
// to a bounded worker pool while enforcing global and per-provider rate limits.
// Skill execution is delegated to an Executor interface so the scheduler is
// transport-agnostic — the same engine drives both the embedded stdio transport
// and the gRPC service mode.
package scheduler

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"math/rand"
	"time"

	"github.com/org/orchestrator/internal/ratelimit"
	"github.com/org/orchestrator/internal/report"
	"github.com/org/orchestrator/internal/spec"
)

// ---------------------------------------------------------------------------
// Executor interface — implemented by transports (stdio, grpc)
// ---------------------------------------------------------------------------

// Invocation is handed to an Executor to run one skill call.
type Invocation struct {
	RunID        string
	TaskID       string
	Skill        string
	InputsJSON   string
	Attempt      int
	InvocationID string
}

// Decision mirrors report.Decision but carries raw JSON data from the client.
type Decision struct {
	AtMs      int64  `json:"at_ms"`
	Summary   string `json:"summary"`
	Rationale string `json:"rationale,omitempty"`
	DataJSON  string `json:"data_json,omitempty"`
}

// LLMUsage mirrors report.LLMUsage at the transport layer.
type LLMUsage struct {
	Provider  string `json:"provider"`
	Model     string `json:"model"`
	TokensIn  int64  `json:"tokens_in"`
	TokensOut int64  `json:"tokens_out"`
}

// SkillError is a typed failure from the skill handler.
type SkillError struct {
	Type      string `json:"type"`
	Message   string `json:"message"`
	Retryable bool   `json:"retryable"`
}

func (e *SkillError) Error() string { return fmt.Sprintf("%s: %s", e.Type, e.Message) }

// Result is what the Executor returns for one Invocation.
type Result struct {
	InvocationID string
	OutputJSON   string      // non-empty on success
	Err          *SkillError // non-nil on failure
	Decisions    []Decision
	LLMUsage     *LLMUsage
	ToolCalls    int64
}

// Executor runs a skill invocation and blocks until it completes or ctx is done.
type Executor interface {
	Execute(ctx context.Context, inv Invocation) (Result, error)
}

// ---------------------------------------------------------------------------
// Events — streamed to callers during execution
// ---------------------------------------------------------------------------

type EventType string

const (
	EventTaskStarted   EventType = "task.started"
	EventTaskSucceeded EventType = "task.succeeded"
	EventTaskFailed    EventType = "task.failed"
	EventTaskSkipped   EventType = "task.skipped"
)

type Event struct {
	Type     EventType
	RunID    string
	TaskID   string
	AtUnixMs int64
}

// ---------------------------------------------------------------------------
// Scheduler
// ---------------------------------------------------------------------------

type Scheduler struct {
	wf     *spec.Workflow
	events chan<- Event // nil = no streaming
}

func New(wf *spec.Workflow, events chan<- Event) *Scheduler {
	return &Scheduler{wf: wf, events: events}
}

// taskDone is sent by goroutines back to the main loop.
type taskDone struct{ span *report.TaskSpan }

// Run executes the workflow and returns the final report.
func (s *Scheduler) Run(ctx context.Context, runID string, inputs map[string]any, exec Executor) (*report.Report, error) {
	if inputs == nil {
		inputs = map[string]any{}
	}
	startedAt := time.Now()

	taskMap := s.wf.TaskMap()

	// DAG bookkeeping (main-loop-only; no concurrent writes needed).
	indeg := make(map[string]int, len(s.wf.Tasks))
	children := make(map[string][]string, len(s.wf.Tasks))
	for _, t := range s.wf.Tasks {
		indeg[t.ID] = len(t.DependsOn)
		for _, dep := range t.DependsOn {
			children[dep] = append(children[dep], t.ID)
		}
	}

	// dependsOnMap is used for critical-path after the run.
	dependsOnMap := make(map[string][]string, len(s.wf.Tasks))
	for _, t := range s.wf.Tasks {
		dependsOnMap[t.ID] = t.DependsOn
	}

	// Rate limiters.
	var globalLimiter ratelimit.Limiter = ratelimit.NullBucket{}
	if rl := s.wf.RateLimit; rl != nil {
		globalLimiter = ratelimit.New(float64(rl.Requests), float64(rl.Per), "global")
	}
	provLimiters := make(map[string]ratelimit.Limiter, len(s.wf.Providers))
	for name, p := range s.wf.Providers {
		if p.RateLimit != nil {
			provLimiters[name] = ratelimit.New(float64(p.RateLimit.Requests), float64(p.RateLimit.Per), name)
		} else {
			provLimiters[name] = ratelimit.NullBucket{}
		}
	}

	sem := make(chan struct{}, s.wf.MaxParallel)
	doneCh := make(chan taskDone, len(s.wf.Tasks)+4)

	// Completed task outputs — read/written only in the main goroutine.
	results := make(map[string]any, len(s.wf.Tasks))
	spans := make(map[string]*report.TaskSpan, len(s.wf.Tasks))
	var totals report.Totals
	var errors []string

	runCtx, cancelRun := context.WithCancel(ctx)
	defer cancelRun()

	// Initial ready set.
	ready := make([]string, 0, len(s.wf.Tasks))
	for _, t := range s.wf.Tasks {
		if indeg[t.ID] == 0 {
			ready = append(ready, t.ID)
		}
	}

	inFlight := 0
	runFailed := false

	// Dispatch launches a goroutine for task t.
	// resultSnapshot is a read-only copy of results at dispatch time — safe to
	// pass to a goroutine without sharing the live map.
	dispatch := func(t *spec.Task, resultSnapshot map[string]any) {
		inFlight++
		s.emit(Event{Type: EventTaskStarted, RunID: runID, TaskID: t.ID, AtUnixMs: nowMs()})
		go func() {
			span := executeTask(runCtx, runID, s.wf, t, inputs, resultSnapshot, sem, globalLimiter, provLimiters, exec)
			doneCh <- taskDone{span: span}
		}()
	}

	markAllUndispatchedSkipped := func() {
		for _, t := range s.wf.Tasks {
			if _, exists := spans[t.ID]; !exists {
				spans[t.ID] = &report.TaskSpan{ID: t.ID, Status: "skipped"}
				s.emit(Event{Type: EventTaskSkipped, RunID: runID, TaskID: t.ID, AtUnixMs: nowMs()})
			}
		}
	}

	markDescendantsSkipped := func(fromID string) {
		stack := append([]string{}, children[fromID]...)
		seen := map[string]bool{}
		for len(stack) > 0 {
			cid := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			if seen[cid] || spans[cid] != nil {
				continue
			}
			seen[cid] = true
			spans[cid] = &report.TaskSpan{ID: cid, Status: "skipped"}
			s.emit(Event{Type: EventTaskSkipped, RunID: runID, TaskID: cid, AtUnixMs: nowMs()})
			stack = append(stack, children[cid]...)
		}
	}

	// Main loop — single goroutine, no shared-state races.
	for len(ready) > 0 || inFlight > 0 {
		// Dispatch all currently ready tasks with a snapshot of results.
		for len(ready) > 0 {
			tid := ready[0]
			ready = ready[1:]
			dispatch(taskMap[tid], copyMap(results))
		}

		// Block until at least one task finishes.
		d := <-doneCh
		inFlight--
		span := d.span
		spans[span.ID] = span

		evType := EventTaskSucceeded
		if span.Status != "succeeded" {
			evType = EventTaskFailed
		}
		s.emit(Event{Type: evType, RunID: runID, TaskID: span.ID, AtUnixMs: nowMs()})

		totals.Retries += int64(span.Attempts - 1)
		if span.LLM != nil {
			totals.LLMTokensIn += span.LLM.TokensIn
			totals.LLMTokensOut += span.LLM.TokensOut
		}

		if span.Status == "succeeded" {
			results[span.ID] = span.Output
			for _, cid := range children[span.ID] {
				indeg[cid]--
				if indeg[cid] == 0 {
					ready = append(ready, cid)
				}
			}
		} else {
			errors = append(errors, span.Error)
			onError := taskMap[span.ID].EffectiveOnError(s.wf.DefaultOnError)
			if onError == "fail_fast" {
				runFailed = true
				cancelRun()
				// Drain remaining in-flight goroutines.
				for inFlight > 0 {
					d2 := <-doneCh
					inFlight--
					spans[d2.span.ID] = d2.span
				}
				ready = nil
				markAllUndispatchedSkipped()
				break
			}
			markDescendantsSkipped(span.ID)
		}
	}

	// Determine overall status.
	status := "succeeded"
	if runFailed {
		status = "failed"
	} else {
		for _, sp := range spans {
			if sp.Status == "failed" {
				status = "failed"
				break
			}
		}
	}

	// Resolve workflow output.
	var output any
	if status == "succeeded" && s.wf.Output != "" {
		scope := buildScope(inputs, results)
		if v, err := spec.Resolve(s.wf.Output, scope); err == nil {
			output = v
		}
	}

	// Build task list in spec order.
	ordered := make([]*report.TaskSpan, 0, len(s.wf.Tasks))
	for _, t := range s.wf.Tasks {
		if sp, ok := spans[t.ID]; ok {
			ordered = append(ordered, sp)
		}
	}

	return &report.Report{
		Workflow:     s.wf.Name,
		RunID:        runID,
		Status:       status,
		StartedAt:    startedAt.UTC().Format(time.RFC3339),
		DurationMs:   time.Since(startedAt).Milliseconds(),
		Tasks:        ordered,
		CriticalPath: report.CriticalPath(spans, dependsOnMap),
		Totals:       totals,
		Errors:       errors,
		Output:       output,
	}, nil
}

// ---------------------------------------------------------------------------
// Task execution (runs in its own goroutine)
// ---------------------------------------------------------------------------

// executeTask runs task t to completion (with retries) and returns its span.
// resultSnapshot is a stable copy of completed task outputs provided at dispatch
// time; it is safe to read without synchronisation.
func executeTask(
	ctx context.Context, runID string, wf *spec.Workflow, t *spec.Task,
	inputs map[string]any, resultSnapshot map[string]any,
	sem chan struct{},
	global ratelimit.Limiter, prov map[string]ratelimit.Limiter,
	exec Executor,
) *report.TaskSpan {
	retry := t.EffectiveRetry(wf.DefaultRetry)
	timeout := t.EffectiveTimeout(wf.DefaultTimeout)

	// Resolve inputs once using the stable snapshot.
	scope := buildScope(inputs, resultSnapshot)
	resolved, err := spec.Resolve(t.Inputs, scope)
	if err != nil {
		return &report.TaskSpan{ID: t.ID, Status: "failed", Attempts: 1, Error: err.Error()}
	}
	inputsJSON, _ := json.Marshal(resolved)

	span := &report.TaskSpan{ID: t.ID, Status: "failed"}
	t0 := time.Now()

	for attempt := 1; attempt <= retry.Max+1; attempt++ {
		span.Attempts = attempt

		// Acquire concurrency slot.
		select {
		case <-ctx.Done():
			span.Status = "skipped"
			span.Error = "cancelled"
			span.DurationMs = time.Since(t0).Milliseconds()
			return span
		case sem <- struct{}{}:
		}

		// Acquire global rate token.
		if err := global.Acquire(ctx); err != nil {
			<-sem
			span.Status = "skipped"
			span.Error = "cancelled"
			span.DurationMs = time.Since(t0).Milliseconds()
			return span
		}

		// Acquire provider rate token.
		if t.Provider != "" {
			if pl, ok := prov[t.Provider]; ok {
				if err := pl.Acquire(ctx); err != nil {
					<-sem
					span.Status = "skipped"
					span.Error = "cancelled"
					span.DurationMs = time.Since(t0).Milliseconds()
					return span
				}
			}
		}

		inv := Invocation{
			RunID:        runID,
			TaskID:       t.ID,
			Skill:        t.Skill,
			InputsJSON:   string(inputsJSON),
			Attempt:      attempt,
			InvocationID: fmt.Sprintf("%s-%s-%d", runID, t.ID, attempt),
		}

		execCtx := ctx
		var cancelTimeout context.CancelFunc
		if timeout != nil {
			d := time.Duration(float64(time.Second) * float64(*timeout))
			execCtx, cancelTimeout = context.WithTimeout(ctx, d)
		}

		result, execErr := exec.Execute(execCtx, inv)
		if cancelTimeout != nil {
			cancelTimeout()
		}
		<-sem // release concurrency slot

		// Merge per-attempt decisions and LLM usage.
		span.Decisions = append(span.Decisions, convertDecisions(result.Decisions)...)
		if result.LLMUsage != nil {
			if span.LLM == nil {
				span.LLM = &report.LLMUsage{
					Provider: result.LLMUsage.Provider,
					Model:    result.LLMUsage.Model,
				}
			}
			span.LLM.TokensIn += result.LLMUsage.TokensIn
			span.LLM.TokensOut += result.LLMUsage.TokensOut
		}

		if execErr != nil {
			span.Error = execErr.Error()
			if attempt <= retry.Max {
				sleepWithJitter(retry, attempt)
				continue
			}
			span.DurationMs = time.Since(t0).Milliseconds()
			return span
		}

		if result.Err != nil {
			span.Error = result.Err.Error()
			retryable := result.Err.Retryable || attempt <= retry.Max
			if retryable && attempt <= retry.Max {
				sleepWithJitter(retry, attempt)
				continue
			}
			span.DurationMs = time.Since(t0).Milliseconds()
			return span
		}

		// Success.
		var output any
		if result.OutputJSON != "" {
			if err := json.Unmarshal([]byte(result.OutputJSON), &output); err != nil {
				output = result.OutputJSON // treat as raw string
			}
		}
		span.Status = "succeeded"
		span.Output = output
		span.DurationMs = time.Since(t0).Milliseconds()
		return span
	}

	span.DurationMs = time.Since(t0).Milliseconds()
	return span
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func buildScope(inputs map[string]any, results map[string]any) map[string]any {
	scope := map[string]any{"input": inputs}
	for id, out := range results {
		scope[id] = map[string]any{"output": out}
	}
	return scope
}

// copyMap returns a shallow copy of m. Used to snapshot results at dispatch time
// so goroutines can read without sharing the live map.
func copyMap(m map[string]any) map[string]any {
	cp := make(map[string]any, len(m))
	for k, v := range m {
		cp[k] = v
	}
	return cp
}

func sleepWithJitter(r spec.Retry, attempt int) {
	var base float64
	switch r.Backoff {
	case "none":
		return
	case "fixed":
		base = float64(r.Base)
	default: // exponential
		base = float64(r.Base) * math.Pow(2, float64(attempt-1))
	}
	if r.Jitter && base > 0 {
		base = base * (0.5 + rand.Float64()/2)
	}
	if base > 0 {
		time.Sleep(time.Duration(base * float64(time.Second)))
	}
}

func convertDecisions(ds []Decision) []report.Decision {
	if len(ds) == 0 {
		return nil
	}
	out := make([]report.Decision, len(ds))
	for i, d := range ds {
		out[i] = report.Decision{AtMs: d.AtMs, Summary: d.Summary, Rationale: d.Rationale}
		if d.DataJSON != "" {
			var data any
			if err := json.Unmarshal([]byte(d.DataJSON), &data); err == nil {
				out[i].Data = data
			}
		}
	}
	return out
}

func nowMs() int64 {
	return time.Now().UnixNano() / int64(time.Millisecond)
}

func (s *Scheduler) emit(e Event) {
	if s.events != nil {
		select {
		case s.events <- e:
		default: // never block on event delivery
		}
	}
}
