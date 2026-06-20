package report

import (
	"encoding/json"
	"testing"
)

func span(id, status string, durationMs int64) *TaskSpan {
	return &TaskSpan{ID: id, Status: status, DurationMs: durationMs}
}

func TestCriticalPath_linear(t *testing.T) {
	spans := map[string]*TaskSpan{
		"a": span("a", "succeeded", 100),
		"b": span("b", "succeeded", 200),
		"c": span("c", "succeeded", 50),
	}
	deps := map[string][]string{
		"a": {},
		"b": {"a"},
		"c": {"b"},
	}
	cp := CriticalPath(spans, deps)
	want := []string{"a", "b", "c"}
	if len(cp) != len(want) {
		t.Fatalf("want %v got %v", want, cp)
	}
	for i, id := range want {
		if cp[i] != id {
			t.Errorf("cp[%d]: want %s got %s", i, id, cp[i])
		}
	}
}

func TestCriticalPath_parallel_join(t *testing.T) {
	// a(100ms) ─┐
	//            ├─ c(50ms)  critical path = a → c (150ms) not b → c (250ms)
	// b(200ms) ─┘
	spans := map[string]*TaskSpan{
		"a": span("a", "succeeded", 100),
		"b": span("b", "succeeded", 200),
		"c": span("c", "succeeded", 50),
	}
	deps := map[string][]string{
		"a": {},
		"b": {},
		"c": {"a", "b"},
	}
	cp := CriticalPath(spans, deps)
	// Longest chain by total duration: b(200) + c(50) = 250
	if len(cp) == 0 || cp[len(cp)-1] != "c" {
		t.Fatalf("expected path ending in c, got %v", cp)
	}
	if cp[0] != "b" {
		t.Errorf("expected path to start with b (longest dep), got %v", cp)
	}
}

func TestCriticalPath_with_failed(t *testing.T) {
	spans := map[string]*TaskSpan{
		"a": span("a", "succeeded", 100),
		"b": span("b", "failed", 200),
	}
	deps := map[string][]string{"a": {}, "b": {}}
	cp := CriticalPath(spans, deps)
	// Only succeeded tasks count.
	if len(cp) != 1 || cp[0] != "a" {
		t.Errorf("expected [a], got %v", cp)
	}
}

func TestReport_JSONSerialization(t *testing.T) {
	rep := &Report{
		Workflow:   "test",
		RunID:      "r_1",
		Status:     "succeeded",
		DurationMs: 500,
		Tasks: []*TaskSpan{
			{ID: "a", Status: "succeeded", DurationMs: 100, Attempts: 1,
				Decisions: []Decision{{AtMs: 50, Summary: "chose X", Rationale: "fastest"}},
				LLM:       &LLMUsage{Provider: "mock", Model: "m1", TokensIn: 10, TokensOut: 5},
			},
		},
		CriticalPath: []string{"a"},
		Totals:       Totals{LLMTokensIn: 10, LLMTokensOut: 5},
		Errors:       []string{},
	}

	b, err := json.Marshal(rep)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}

	var got map[string]any
	if err := json.Unmarshal(b, &got); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	if got["status"] != "succeeded" {
		t.Errorf("status: %v", got["status"])
	}
	tasks := got["tasks"].([]any)
	if len(tasks) != 1 {
		t.Fatalf("expected 1 task, got %d", len(tasks))
	}
	task := tasks[0].(map[string]any)
	if task["id"] != "a" {
		t.Errorf("task id: %v", task["id"])
	}
	// Output field must NOT appear in JSON (tagged json:"-").
	if _, ok := task["output"]; ok {
		t.Error("output field should not appear in serialized TaskSpan")
	}
}
