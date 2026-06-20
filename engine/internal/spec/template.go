package spec

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
)

var templateRE = regexp.MustCompile(`\$\{([^}]+)\}`)

// Resolve substitutes ${...} expressions in value using scope.
//
// Supported paths:
//   - input.<field>       — from workflow inputs
//   - <taskId>.output     — full output of a completed task
//   - <taskId>.output.<field...> — nested field
//
// A string that is exactly one reference returns the referenced value preserving
// its type; otherwise all references are substituted as JSON text.
func Resolve(value any, scope map[string]any) (any, error) {
	switch v := value.(type) {
	case map[string]any:
		out := make(map[string]any, len(v))
		for k, val := range v {
			r, err := Resolve(val, scope)
			if err != nil {
				return nil, err
			}
			out[k] = r
		}
		return out, nil
	case []any:
		out := make([]any, len(v))
		for i, val := range v {
			r, err := Resolve(val, scope)
			if err != nil {
				return nil, err
			}
			out[i] = r
		}
		return out, nil
	case string:
		// Exact single reference → preserve type.
		if m := templateRE.FindStringSubmatch(strings.TrimSpace(v)); m != nil && m[0] == strings.TrimSpace(v) {
			return lookup(strings.TrimSpace(m[1]), scope)
		}
		// Inline substitution → stringify.
		var subErr error
		result := templateRE.ReplaceAllStringFunc(v, func(match string) string {
			if subErr != nil {
				return match
			}
			key := templateRE.FindStringSubmatch(match)[1]
			val, err := lookup(strings.TrimSpace(key), scope)
			if err != nil {
				subErr = err
				return match
			}
			if s, ok := val.(string); ok {
				return s
			}
			b, _ := json.Marshal(val)
			return string(b)
		})
		if subErr != nil {
			return nil, subErr
		}
		return result, nil
	default:
		return v, nil
	}
}

func lookup(path string, scope map[string]any) (any, error) {
	parts := strings.SplitN(path, ".", -1)
	var node any = scope
	for _, p := range parts {
		m, ok := node.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("template: cannot traverse into non-object at %q in path %q", p, path)
		}
		val, exists := m[p]
		if !exists {
			return nil, fmt.Errorf("template: unresolved reference ${%s}", path)
		}
		node = val
	}
	return node, nil
}
