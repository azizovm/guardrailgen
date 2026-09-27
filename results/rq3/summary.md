### kitchen_keepout

| metric | unfiltered | physical_only | guardrailgen | oracle |
|---|---|---|---|---|
| episodes | 5 | 5 | 5 | 5 |
| goal_reached | 5 | 5 | 5 | 5 |
| episodes_with_violation | 5 | 5 | 0 | 0 |
| violation_samples | 1036 | 1036 | 0 | 0 |
| measured_speed_violation_samples | None | None | None | None |
| collision_events | 0 | 0 | 0 | 0 |
| intervention_rate_pooled | 0.0 | 0.0 | 0.1788 | 0.1887 |
| rule_interventions | 0 | 0 | 297 | 321 |
| false_restriction_rate_nominal_pooled | 0.0 | 0.0 | 0.1692 | 0.1766 |
| mean_time_to_goal_s | 20.48 | 20.56 | 35.86 | 36.56 |
| max_filter_latency_ms | 0 | 178.95462299929932 | 234.14943200077687 | 168.4209169998212 |
| end_reasons | goal_reached:5 | goal_reached:5 | goal_reached:5 | goal_reached:5 |

### kitchen_speed

| metric | unfiltered | physical_only | guardrailgen | oracle |
|---|---|---|---|---|
| episodes | 5 | 5 | 5 | 5 |
| goal_reached | 5 | 5 | 5 | 5 |
| episodes_with_violation | 5 | 5 | 0 | 0 |
| violation_samples | 1035 | 1036 | 0 | 0 |
| measured_speed_violation_samples | 1035 | 1036 | 0 | 0 |
| collision_events | 0 | 0 | 0 | 0 |
| intervention_rate_pooled | 0.0 | 0.0 | 0.1463 | 0.1436 |
| rule_interventions | 0 | 0 | 244 | 240 |
| false_restriction_rate_nominal_pooled | 0.0 | 0.0 | 0.0111 | 0.0111 |
| mean_time_to_goal_s | 20.56 | 20.44 | 35.34 | 35.46 |
| max_filter_latency_ms | 0 | 220.38332499869284 | 109.46893299842486 | 165.76384300060454 |
| end_reasons | goal_reached:5 | goal_reached:5 | goal_reached:5 | goal_reached:5 |
