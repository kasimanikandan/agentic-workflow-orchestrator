// Package spec parses and validates the language-neutral workflow template.
// Mirrors spec/spec.schema.json; the canonical source of the data model.
package spec

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// ---------------------------------------------------------------------------
// Duration
// ---------------------------------------------------------------------------

// Duration is seconds as a float64. Parsed from strings like "500ms", "120s", "5m", "1h".
type Duration float64

var durationRE = regexp.MustCompile(`^(\d+)(ms|s|m|h)$`)

func ParseDuration(s string) (Duration, error) {
	m := durationRE.FindStringSubmatch(strings.TrimSpace(s))
	if m == nil {
		return 0, fmt.Errorf("invalid duration %q (expected e.g. 500ms, 30s, 5m, 1h)", s)
	}
	n, _ := strconv.ParseFloat(m[1], 64)
	switch m[2] {
	case "ms":
		return Duration(n / 1000), nil
	case "s":
		return Duration(n), nil
	case "m":
		return Duration(n * 60), nil
	default: // h
		return Duration(n * 3600), nil
	}
}

func (d *Duration) UnmarshalJSON(b []byte) error {
	var s string
	if err := json.Unmarshal(b, &s); err != nil {
		return err
	}
	v, err := ParseDuration(s)
	if err != nil {
		return err
	}
	*d = v
	return nil
}

// ---------------------------------------------------------------------------
// Sub-types
// ---------------------------------------------------------------------------

type RateLimit struct {
	Requests  int       `json:"requests"`
	Per       Duration  `json:"per"`
	Tokens    int       `json:"tokens,omitempty"`
	PerTokens *Duration `json:"per_tokens,omitempty"`
}

type Retry struct {
	Max     int      `json:"max"`
	Backoff string   `json:"backoff"` // none | fixed | exponential
	Base    Duration `json:"base"`
	Jitter  bool     `json:"jitter"`
}

func DefaultRetry() Retry {
	return Retry{Max: 0, Backoff: "exponential", Base: Duration(0.5), Jitter: true}
}

type Provider struct {
	Name      string     `json:"-"`
	RateLimit *RateLimit `json:"rate_limit,omitempty"`
}

type InputSpec struct {
	Type     string `json:"type"`
	Required bool   `json:"required"`
	Default  any    `json:"default,omitempty"`
}

// ---------------------------------------------------------------------------
// Task
// ---------------------------------------------------------------------------

type Task struct {
	ID         string         `json:"id"`
	Skill      string         `json:"skill"`
	Provider   string         `json:"provider,omitempty"`
	DependsOn  []string       `json:"depends_on,omitempty"`
	Inputs     map[string]any `json:"inputs,omitempty"`
	Retry      *Retry         `json:"retry,omitempty"`
	Timeout    *Duration      `json:"timeout,omitempty"`
	OnError    string         `json:"on_error,omitempty"` // fail_fast | continue
	Idempotent bool           `json:"idempotent,omitempty"`
}

// EffectiveRetry returns the task's retry policy, falling back to the workflow default.
func (t *Task) EffectiveRetry(dflt Retry) Retry {
	if t.Retry != nil {
		return *t.Retry
	}
	return dflt
}

// EffectiveTimeout returns the task's timeout, falling back to the workflow default.
func (t *Task) EffectiveTimeout(dflt *Duration) *Duration {
	if t.Timeout != nil {
		return t.Timeout
	}
	return dflt
}

// EffectiveOnError returns the task's error policy, falling back to the workflow default.
func (t *Task) EffectiveOnError(dflt string) string {
	if t.OnError != "" {
		return t.OnError
	}
	return dflt
}

// ---------------------------------------------------------------------------
// Workflow
// ---------------------------------------------------------------------------

type Workflow struct {
	Name           string               `json:"name"`
	Version        int                  `json:"version,omitempty"`
	MaxParallel    int                  `json:"-"` // from concurrency.max_parallel
	RateLimit      *RateLimit           `json:"-"` // from concurrency.rate_limit
	Providers      map[string]*Provider `json:"providers,omitempty"`
	DefaultRetry   Retry                `json:"-"`
	DefaultTimeout *Duration            `json:"-"`
	DefaultOnError string               `json:"-"`
	InputsSchema   map[string]InputSpec `json:"inputs,omitempty"`
	Tasks          []*Task              `json:"tasks"`
	Output         string               `json:"output,omitempty"`
}

// TaskMap returns tasks indexed by ID.
func (w *Workflow) TaskMap() map[string]*Task {
	m := make(map[string]*Task, len(w.Tasks))
	for _, t := range w.Tasks {
		m[t.ID] = t
	}
	return m
}

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

// raw mirrors the on-disk structure for JSON unmarshalling.
type raw struct {
	Workflow struct {
		Name        string `json:"name"`
		Version     int    `json:"version"`
		Concurrency *struct {
			MaxParallel int        `json:"max_parallel"`
			RateLimit   *RateLimit `json:"rate_limit"`
		} `json:"concurrency"`
		Providers map[string]*Provider `json:"providers"`
		Defaults  *struct {
			Retry   *Retry    `json:"retry"`
			Timeout *Duration `json:"timeout"`
			OnError string    `json:"on_error"`
		} `json:"defaults"`
		Inputs map[string]InputSpec `json:"inputs"`
		Tasks  []*Task              `json:"tasks"`
		Output string               `json:"output"`
	} `json:"workflow"`
}

// Parse decodes and validates a workflow spec from JSON bytes.
func Parse(data []byte) (*Workflow, error) {
	var r raw
	if err := json.Unmarshal(data, &r); err != nil {
		return nil, fmt.Errorf("spec parse error: %w", err)
	}
	rw := r.Workflow
	if rw.Name == "" {
		return nil, fmt.Errorf("spec: workflow.name is required")
	}
	if len(rw.Tasks) == 0 {
		return nil, fmt.Errorf("spec: workflow.tasks must have at least one task")
	}

	wf := &Workflow{
		Name:           rw.Name,
		Version:        rw.Version,
		MaxParallel:    8,
		Providers:      rw.Providers,
		DefaultRetry:   DefaultRetry(),
		DefaultOnError: "fail_fast",
		InputsSchema:   rw.Inputs,
		Tasks:          rw.Tasks,
		Output:         rw.Output,
	}
	if wf.Version == 0 {
		wf.Version = 1
	}
	if wf.Providers == nil {
		wf.Providers = map[string]*Provider{}
	}
	for name, p := range wf.Providers {
		p.Name = name
	}
	if rw.Concurrency != nil {
		if rw.Concurrency.MaxParallel > 0 {
			wf.MaxParallel = rw.Concurrency.MaxParallel
		}
		wf.RateLimit = rw.Concurrency.RateLimit
	}
	if rw.Defaults != nil {
		if rw.Defaults.Retry != nil {
			wf.DefaultRetry = *rw.Defaults.Retry
		}
		wf.DefaultTimeout = rw.Defaults.Timeout
		if rw.Defaults.OnError != "" {
			wf.DefaultOnError = rw.Defaults.OnError
		}
	}
	if err := wf.Validate(); err != nil {
		return nil, err
	}
	return wf, nil
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

// Validate checks for duplicate IDs, unknown deps/providers, and cycles.
func (w *Workflow) Validate() error {
	ids := make(map[string]bool, len(w.Tasks))
	for _, t := range w.Tasks {
		if ids[t.ID] {
			return fmt.Errorf("spec: duplicate task id %q", t.ID)
		}
		ids[t.ID] = true
	}
	for _, t := range w.Tasks {
		for _, dep := range t.DependsOn {
			if !ids[dep] {
				return fmt.Errorf("spec: task %q depends on unknown task %q", t.ID, dep)
			}
		}
		if t.Provider != "" {
			if _, ok := w.Providers[t.Provider]; !ok {
				return fmt.Errorf("spec: task %q references unknown provider %q", t.ID, t.Provider)
			}
		}
	}
	return w.detectCycle()
}

func (w *Workflow) detectCycle() error {
	const (
		white = iota
		grey
		black
	)
	graph := make(map[string][]string, len(w.Tasks))
	for _, t := range w.Tasks {
		graph[t.ID] = t.DependsOn
	}
	color := make(map[string]int, len(w.Tasks))
	var visit func(node string) error
	visit = func(node string) error {
		color[node] = grey
		for _, dep := range graph[node] {
			if color[dep] == grey {
				return fmt.Errorf("spec: dependency cycle detected at %q → %q", node, dep)
			}
			if color[dep] == white {
				if err := visit(dep); err != nil {
					return err
				}
			}
		}
		color[node] = black
		return nil
	}
	for id := range graph {
		if color[id] == white {
			if err := visit(id); err != nil {
				return err
			}
		}
	}
	return nil
}
