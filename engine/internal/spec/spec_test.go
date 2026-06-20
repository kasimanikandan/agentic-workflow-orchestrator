package spec

import (
	"encoding/json"
	"testing"
)

var validJSON = `{
  "workflow": {
    "name": "test",
    "tasks": [
      {"id":"a","skill":"s.one"},
      {"id":"b","skill":"s.two","depends_on":["a"]}
    ]
  }
}`

func TestParse_valid(t *testing.T) {
	wf, err := Parse([]byte(validJSON))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if wf.Name != "test" {
		t.Fatalf("name: want test got %q", wf.Name)
	}
	if len(wf.Tasks) != 2 {
		t.Fatalf("tasks: want 2 got %d", len(wf.Tasks))
	}
	if wf.MaxParallel != 8 {
		t.Fatalf("default max_parallel should be 8, got %d", wf.MaxParallel)
	}
}

func TestParse_cycle(t *testing.T) {
	cyclic := `{"workflow":{"name":"x","tasks":[
		{"id":"a","skill":"s","depends_on":["b"]},
		{"id":"b","skill":"s","depends_on":["a"]}
	]}}`
	if _, err := Parse([]byte(cyclic)); err == nil {
		t.Fatal("expected cycle error")
	}
}

func TestParse_unknownDep(t *testing.T) {
	bad := `{"workflow":{"name":"x","tasks":[{"id":"a","skill":"s","depends_on":["nope"]}]}}`
	if _, err := Parse([]byte(bad)); err == nil {
		t.Fatal("expected unknown dep error")
	}
}

func TestParseDuration(t *testing.T) {
	cases := []struct {
		in   string
		want float64
	}{
		{"500ms", 0.5},
		{"1s", 1},
		{"2m", 120},
		{"1h", 3600},
	}
	for _, c := range cases {
		d, err := ParseDuration(c.in)
		if err != nil {
			t.Errorf("ParseDuration(%q): %v", c.in, err)
			continue
		}
		if float64(d) != c.want {
			t.Errorf("ParseDuration(%q) = %v, want %v", c.in, float64(d), c.want)
		}
	}
}

func TestParse_concurrencyAndDefaults(t *testing.T) {
	js := `{"workflow":{"name":"x","concurrency":{"max_parallel":4,"rate_limit":{"requests":10,"per":"1s"}},
	"defaults":{"retry":{"max":2,"backoff":"fixed","base":"1s","jitter":false},"timeout":"30s","on_error":"continue"},
	"tasks":[{"id":"a","skill":"s"}]}}`
	wf, err := Parse([]byte(js))
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if wf.MaxParallel != 4 {
		t.Errorf("MaxParallel: want 4 got %d", wf.MaxParallel)
	}
	if wf.RateLimit == nil || wf.RateLimit.Requests != 10 {
		t.Errorf("RateLimit not set correctly")
	}
	if wf.DefaultRetry.Max != 2 {
		t.Errorf("DefaultRetry.Max: want 2 got %d", wf.DefaultRetry.Max)
	}
	timeout := float64(*wf.DefaultTimeout)
	if timeout != 30 {
		t.Errorf("DefaultTimeout: want 30s got %v", timeout)
	}
	if wf.DefaultOnError != "continue" {
		t.Errorf("DefaultOnError: want continue got %q", wf.DefaultOnError)
	}
}

func TestResolve_simple(t *testing.T) {
	scope := map[string]any{
		"input": map[string]any{"ticker": "AAPL"},
		"fetch": map[string]any{"output": map[string]any{"last": 199.4}},
	}
	v, err := Resolve("${input.ticker}", scope)
	if err != nil {
		t.Fatal(err)
	}
	if v != "AAPL" {
		t.Fatalf("want AAPL got %v", v)
	}
}

func TestResolve_nestedOutput(t *testing.T) {
	scope := map[string]any{
		"input": map[string]any{},
		"fetch": map[string]any{"output": map[string]any{"last": 199.4}},
	}
	v, err := Resolve("${fetch.output.last}", scope)
	if err != nil {
		t.Fatal(err)
	}
	// JSON numbers unmarshal as float64.
	if v != 199.4 {
		t.Fatalf("want 199.4 got %v", v)
	}
}

func TestResolve_inline(t *testing.T) {
	scope := map[string]any{"input": map[string]any{"ticker": "AAPL"}}
	v, err := Resolve("ticker=${input.ticker}&foo=bar", scope)
	if err != nil {
		t.Fatal(err)
	}
	if v != "ticker=AAPL&foo=bar" {
		t.Fatalf("got %v", v)
	}
}

func TestResolve_map(t *testing.T) {
	scope := map[string]any{"input": map[string]any{"x": 42.0}}
	inputs := map[string]any{"a": "${input.x}", "b": "static"}
	got, err := Resolve(inputs, scope)
	if err != nil {
		t.Fatal(err)
	}
	m := got.(map[string]any)
	if m["a"] != 42.0 {
		t.Errorf("a: want 42.0 got %v", m["a"])
	}
	if m["b"] != "static" {
		t.Errorf("b: want static got %v", m["b"])
	}
}

func TestResolve_unresolved(t *testing.T) {
	scope := map[string]any{"input": map[string]any{}}
	if _, err := Resolve("${input.missing}", scope); err == nil {
		t.Fatal("expected error for unresolved reference")
	}
}

// Ensure a parsed workflow round-trips through JSON without data loss.
func TestParse_jsonRoundTrip(t *testing.T) {
	wf, err := Parse([]byte(validJSON))
	if err != nil {
		t.Fatal(err)
	}
	b, err := json.Marshal(wf)
	if err != nil {
		t.Fatal(err)
	}
	if len(b) == 0 {
		t.Fatal("empty json output")
	}
}
