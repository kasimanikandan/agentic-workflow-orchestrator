// Package report defines the run summary data model and critical-path computation.
package report

// Decision is a critical decision recorded by a skill handler during execution.
type Decision struct {
	AtMs      int64  `json:"at_ms"`
	Summary   string `json:"summary"`
	Rationale string `json:"rationale,omitempty"`
	Data      any    `json:"data,omitempty"`
}

// LLMUsage holds token consumption for one task's LLM calls.
type LLMUsage struct {
	Provider  string `json:"provider"`
	Model     string `json:"model"`
	TokensIn  int64  `json:"tokens_in"`
	TokensOut int64  `json:"tokens_out"`
}

// TaskSpan is the trace for one task execution.
type TaskSpan struct {
	ID         string     `json:"id"`
	Status     string     `json:"status"` // succeeded | failed | skipped
	DurationMs int64      `json:"duration_ms"`
	Attempts   int        `json:"attempts"`
	LLM        *LLMUsage  `json:"llm,omitempty"`
	Decisions  []Decision `json:"decisions,omitempty"`
	Error      string     `json:"error,omitempty"`
	Output     any        `json:"-"` // internal; not serialised in the public report
}

// Totals aggregates resource usage across the whole run.
type Totals struct {
	LLMTokensIn  int64 `json:"llm_tokens_in"`
	LLMTokensOut int64 `json:"llm_tokens_out"`
	ToolCalls    int64 `json:"tool_calls"`
	Retries      int64 `json:"retries"`
}

// Report is the complete summary returned after a workflow run.
type Report struct {
	Workflow     string      `json:"workflow"`
	RunID        string      `json:"run_id"`
	Status       string      `json:"status"` // succeeded | failed | cancelled
	StartedAt    string      `json:"started_at"`
	DurationMs   int64       `json:"duration_ms"`
	Tasks        []*TaskSpan `json:"tasks"`
	CriticalPath []string    `json:"critical_path"`
	Totals       Totals      `json:"totals"`
	Errors       []string    `json:"errors"`
	Output       any         `json:"output,omitempty"`
}

// CriticalPath computes the longest path by cumulative duration through succeeded tasks.
// This is the bottleneck chain — where wall-clock time actually went.
//
// The endpoint is always a sink: a succeeded task that no other succeeded task
// depends on. This ensures the path reaches the final task even when all durations
// are 0ms (fast local runs, tests).
func CriticalPath(spans map[string]*TaskSpan, dependsOn map[string][]string) []string {
	// Count how many succeeded tasks depend on each task. Sinks have count == 0.
	incomingFromSucceeded := map[string]int{}
	for id, s := range spans {
		if s.Status != "succeeded" {
			continue
		}
		for _, dep := range dependsOn[id] {
			if depSpan, ok := spans[dep]; ok && depSpan.Status == "succeeded" {
				incomingFromSucceeded[dep]++
			}
		}
	}

	bestCost := map[string]int64{}
	bestPrev := map[string]string{}
	computed := map[string]bool{}

	var cost func(node string) int64
	cost = func(node string) int64 {
		if computed[node] {
			return bestCost[node]
		}
		computed[node] = true
		span, ok := spans[node]
		var own int64
		if ok && span.Status == "succeeded" {
			own = span.DurationMs
		}
		// -1 ensures the first succeeded dep is always recorded, even with 0ms tasks.
		prevBest := int64(-1)
		prevNode := ""
		for _, dep := range dependsOn[node] {
			if s, exists := spans[dep]; exists && s.Status == "succeeded" {
				c := cost(dep)
				if c > prevBest {
					prevBest = c
					prevNode = dep
				}
			}
		}
		prev := prevBest
		if prev < 0 {
			prev = 0
		}
		bestCost[node] = own + prev
		bestPrev[node] = prevNode
		return bestCost[node]
	}

	// Among sinks, pick the one with the highest cumulative cost.
	// -1 ensures any sink beats the initial value.
	bestTotal := int64(-1)
	var bestEnd string
	for id, s := range spans {
		if s.Status != "succeeded" {
			continue
		}
		if incomingFromSucceeded[id] > 0 {
			continue // not a sink
		}
		c := cost(id)
		if c > bestTotal {
			bestTotal = c
			bestEnd = id
		}
	}
	// Fallback: if no sink found (shouldn't happen in a valid DAG), use any succeeded task.
	if bestEnd == "" {
		for id, s := range spans {
			if s.Status == "succeeded" {
				bestEnd = id
				break
			}
		}
	}
	if bestEnd == "" {
		return nil
	}
	var chain []string
	for node := bestEnd; node != ""; node = bestPrev[node] {
		chain = append(chain, node)
	}
	// Reverse.
	for i, j := 0, len(chain)-1; i < j; i, j = i+1, j-1 {
		chain[i], chain[j] = chain[j], chain[i]
	}
	return chain
}
