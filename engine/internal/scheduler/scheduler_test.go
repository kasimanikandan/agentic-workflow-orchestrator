package scheduler

import (
	"context"
	"fmt"
	"sync/atomic"
	"testing"
	"time"

	"github.com/org/orchestrator/internal/report"
	"github.com/org/orchestrator/internal/spec"
)

// ---------------------------------------------------------------------------
// Mock Executor
// ---------------------------------------------------------------------------

type mockExec struct {
	fn func(ctx context.Context, inv Invocation) (Result, error)
}

func (m *mockExec) Execute(ctx context.Context, inv Invocation) (Result, error) {
	return m.fn(ctx, inv)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func parseWF(t *testing.T, js string) *spec.Workflow {
	t.Helper()
	wf, err := spec.Parse([]byte(js))
	if err != nil {
		t.Fatalf("spec.Parse: %v", err)
	}
	return wf
}

func runWF(t *testing.T, wf *spec.Workflow, inputs map[string]any, exec Executor) *report.Report {
	t.Helper()
	sched := New(wf, nil)
	rep, err := sched.Run(context.Background(), "run-test", inputs, exec)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	return rep
}

func spansByID(rep *report.Report) map[string]*report.TaskSpan {
	m := make(map[string]*report.TaskSpan, len(rep.Tasks))
	for _, ts := range rep.Tasks {
		m[ts.ID] = ts
	}
	return m
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

func TestSerial(t *testing.T) {
	wf := parseWF(t, `{"workflow":{"name":"x","tasks":[
		{"id":"a","skill":"s"},
		{"id":"b","skill":"s","depends_on":["a"]}
	]}}`)

	order := []string{}
	exec := &mockExec{fn: func(_ context.Context, inv Invocation) (Result, error) {
		order = append(order, inv.TaskID)
		return Result{InvocationID: inv.InvocationID, OutputJSON: `"ok"`}, nil
	}}

	rep := runWF(t, wf, nil, exec)
	if rep.Status != "succeeded" {
		t.Fatalf("status: %s", rep.Status)
	}
	if len(order) != 2 || order[0] != "a" || order[1] != "b" {
		t.Fatalf("expected a then b, got %v", order)
	}
}

func TestParallel(t *testing.T) {
	wf := parseWF(t, `{"workflow":{"name":"x","concurrency":{"max_parallel":4},"tasks":[
		{"id":"a","skill":"s"},
		{"id":"b","skill":"s"},
		{"id":"c","skill":"s","depends_on":["a","b"]}
	]}}`)

	var concurrent, peak int64
	exec := &mockExec{fn: func(_ context.Context, inv Invocation) (Result, error) {
		cur := atomic.AddInt64(&concurrent, 1)
		for {
			old := atomic.LoadInt64(&peak)
			if cur <= old || atomic.CompareAndSwapInt64(&peak, old, cur) {
				break
			}
		}
		time.Sleep(30 * time.Millisecond)
		atomic.AddInt64(&concurrent, -1)
		return Result{InvocationID: inv.InvocationID, OutputJSON: `1`}, nil
	}}

	t0 := time.Now()
	rep := runWF(t, wf, nil, exec)
	elapsed := time.Since(t0)

	if rep.Status != "succeeded" {
		t.Fatalf("status: %s", rep.Status)
	}
	// a and b run in parallel: total ~60ms, not 90ms.
	if elapsed > 85*time.Millisecond {
		t.Errorf("expected ~60ms (a∥b then c), got %v", elapsed)
	}
	if peak < 2 {
		t.Errorf("expected peak concurrency ≥2, got %d", peak)
	}
}

func TestConcurrencyLimit(t *testing.T) {
	wf := parseWF(t, `{"workflow":{"name":"x","concurrency":{"max_parallel":1},"tasks":[
		{"id":"a","skill":"s"},{"id":"b","skill":"s"}
	]}}`)

	var concurrent int64
	exec := &mockExec{fn: func(_ context.Context, inv Invocation) (Result, error) {
		cur := atomic.AddInt64(&concurrent, 1)
		defer atomic.AddInt64(&concurrent, -1)
		if cur > 1 {
			return Result{}, fmt.Errorf("limit violated: %d tasks in parallel", cur)
		}
		time.Sleep(20 * time.Millisecond)
		return Result{InvocationID: inv.InvocationID, OutputJSON: `1`}, nil
	}}

	rep := runWF(t, wf, nil, exec)
	if rep.Status != "succeeded" {
		t.Fatalf("status: %s errors: %v", rep.Status, rep.Errors)
	}
}

func TestRetryThenSucceed(t *testing.T) {
	wf := parseWF(t, `{"workflow":{"name":"x","tasks":[
		{"id":"a","skill":"s","retry":{"max":3,"backoff":"none"}}
	]}}`)

	n := 0
	exec := &mockExec{fn: func(_ context.Context, inv Invocation) (Result, error) {
		n++
		if n < 3 {
			return Result{
				InvocationID: inv.InvocationID,
				Err:          &SkillError{Type: "E", Message: "transient", Retryable: true},
			}, nil
		}
		return Result{InvocationID: inv.InvocationID, OutputJSON: `"ok"`}, nil
	}}

	rep := runWF(t, wf, nil, exec)
	if rep.Status != "succeeded" {
		t.Fatalf("status: %s (errors: %v)", rep.Status, rep.Errors)
	}
	if rep.Tasks[0].Attempts != 3 {
		t.Fatalf("expected 3 attempts, got %d", rep.Tasks[0].Attempts)
	}
	if rep.Totals.Retries != 2 {
		t.Fatalf("expected 2 retries, got %d", rep.Totals.Retries)
	}
}

func TestFailFast(t *testing.T) {
	wf := parseWF(t, `{"workflow":{"name":"x","defaults":{"on_error":"fail_fast"},"tasks":[
		{"id":"a","skill":"boom"},
		{"id":"b","skill":"ok","depends_on":["a"]}
	]}}`)

	exec := &mockExec{fn: func(_ context.Context, inv Invocation) (Result, error) {
		if inv.Skill == "boom" {
			return Result{
				InvocationID: inv.InvocationID,
				Err:          &SkillError{Type: "E", Message: "boom"},
			}, nil
		}
		return Result{InvocationID: inv.InvocationID, OutputJSON: `1`}, nil
	}}

	rep := runWF(t, wf, nil, exec)
	if rep.Status != "failed" {
		t.Fatalf("expected failed, got %s", rep.Status)
	}
	by := spansByID(rep)
	if by["a"].Status != "failed" {
		t.Errorf("a: want failed got %s", by["a"].Status)
	}
	if by["b"].Status != "skipped" {
		t.Errorf("b: want skipped got %s", by["b"].Status)
	}
}

func TestContinueOnError(t *testing.T) {
	wf := parseWF(t, `{"workflow":{"name":"x","tasks":[
		{"id":"a","skill":"boom","on_error":"continue"},
		{"id":"b","skill":"ok","depends_on":["a"]},
		{"id":"c","skill":"ok"}
	]}}`)

	exec := &mockExec{fn: func(_ context.Context, inv Invocation) (Result, error) {
		if inv.Skill == "boom" {
			return Result{
				InvocationID: inv.InvocationID,
				Err:          &SkillError{Type: "E", Message: "boom"},
			}, nil
		}
		return Result{InvocationID: inv.InvocationID, OutputJSON: `1`}, nil
	}}

	rep := runWF(t, wf, nil, exec)
	by := spansByID(rep)
	if by["a"].Status != "failed" {
		t.Errorf("a: want failed got %s", by["a"].Status)
	}
	if by["b"].Status != "skipped" {
		t.Errorf("b: want skipped got %s", by["b"].Status)
	}
	if by["c"].Status != "succeeded" {
		t.Errorf("c: want succeeded got %s", by["c"].Status)
	}
}

func TestTemplateResolution(t *testing.T) {
	wf := parseWF(t, `{"workflow":{"name":"x",
		"inputs":{"ticker":{"type":"string","required":true}},
		"tasks":[
			{"id":"fetch","skill":"s","inputs":{"t":"${input.ticker}"}},
			{"id":"use","skill":"s","depends_on":["fetch"],"inputs":{"v":"${fetch.output}"}}
		]}}`)

	exec := &mockExec{fn: func(_ context.Context, inv Invocation) (Result, error) {
		if inv.TaskID == "fetch" {
			if inv.InputsJSON != `{"t":"AAPL"}` {
				return Result{}, fmt.Errorf("fetch inputs wrong: %s", inv.InputsJSON)
			}
			return Result{InvocationID: inv.InvocationID, OutputJSON: `"price:199"`}, nil
		}
		if inv.InputsJSON != `{"v":"price:199"}` {
			return Result{}, fmt.Errorf("use inputs wrong: %s", inv.InputsJSON)
		}
		return Result{InvocationID: inv.InvocationID, OutputJSON: `"ok"`}, nil
	}}

	rep := runWF(t, wf, map[string]any{"ticker": "AAPL"}, exec)
	if rep.Status != "succeeded" {
		t.Fatalf("status: %s errors: %v", rep.Status, rep.Errors)
	}
}
