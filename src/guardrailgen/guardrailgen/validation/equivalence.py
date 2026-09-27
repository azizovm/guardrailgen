"""Reference equivalence for numeric/Boolean point predicates, not English intent.

Constants have exact decimal-rational semantics. This is not a floating-point
implementation proof, a box-verdict equivalence check, or a reachability claim.
Spatial footprint predicates are deliberately outside this affine fragment.
"""
import hashlib
import json
import math
from fractions import Fraction

from guardrailgen.schema import Rule, Scenario, VARIABLES, compile_rule


class UnsupportedFragment(ValueError):
    pass


def _variables(expr):
    if expr['op']=='compare':
        return {expr['variable']}
    if expr['op']=='inside':
        raise UnsupportedFragment('Spatial footprint geometry is outside numeric/Boolean equivalence')
    if expr['op']=='not':
        return _variables(expr['arg'])
    return set().union(*(_variables(child) for child in expr['args']))


def validate_domains(domains, scenario, required=()):
    """Explicit closed, nonempty intervals in schema units; never infer domains."""
    if not isinstance(domains,dict) or not domains:
        raise ValueError('Equivalence requires a nonempty explicit domains object')
    for name,bounds in domains.items():
        if name not in scenario.supported_variables:
            raise ValueError(f'Unsupported domain variable: {name}')
        if not isinstance(bounds,dict) or set(bounds)!={'min','max','unit'}:
            raise ValueError(f'{name} domain requires exactly min, max and unit')
        if bounds['unit']!=VARIABLES[name]['unit']:
            raise ValueError(f'{name} domain requires unit {VARIABLES[name]["unit"]}')
        for value in (bounds['min'],bounds['max']):
            try:
                valid=not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value)
            except OverflowError:
                valid=False
            if not valid:
                raise ValueError(f'{name} domain bounds must be finite numbers')
        if bounds['min']>bounds['max']:
            raise ValueError(f'{name} domain must be nonempty')
    missing=set(required)-set(domains)
    if missing:
        raise ValueError('Missing declared domains: '+', '.join(sorted(missing)))
    return json.loads(json.dumps(domains,allow_nan=False))


def _load_z3():
    import z3
    return z3


def _lower(expr, variables, z3):
    op=expr['op']
    if op=='compare':
        left=variables[expr['variable']]
        right=z3.RealVal(str(expr['value']),ctx=left.ctx)
        return {'lt':left<right,'le':left<=right,'gt':left>right,'ge':left>=right}[expr['comparator']]
    if op=='not':
        return z3.Not(_lower(expr['arg'],variables,z3))
    args=[_lower(child,variables,z3) for child in expr['args']]
    return z3.And(*args) if op=='and' else z3.Or(*args)


def check_equivalence(candidate, reference, scenario, domains, *, timeout_ms=1000):
    """Prove absence of a disagreement, or return an exact rational witness.

    Only `equivalent` is passing evidence. Unknown, unavailable and unsupported
    never become a successful check. A supplied reference is independently
    authored evidence, not automatically a correct interpretation of English.
    """
    if isinstance(timeout_ms,bool) or not isinstance(timeout_ms,int) or not 1<=timeout_ms<=60000:
        raise ValueError('Solver timeout must be an integer from 1 to 60000 ms')
    scenario=Scenario.from_dict(scenario.to_dict())
    candidate=Rule.from_dict(candidate.to_dict(),scenario)
    reference=Rule.from_dict(reference.to_dict(),scenario)
    domains=validate_domains(domains,scenario)
    evidence={'candidate':candidate.to_dict(),'reference':reference.to_dict(),
              'scenario':scenario.to_dict(),'domains':domains}
    report={'status':'not_checked','method':'z3-qf-lra-xor-v1','timeout_ms':timeout_ms,
            'scope':'Point predicate equivalence over explicit closed domains, exact decimal-rational constants',
            'english_semantics_verified':False,'floating_point_implementation_verified':False,
            'reference_rule':reference.to_dict(),'domains':domains,
            'inputs_sha256':hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(',',':'),
                ensure_ascii=False,allow_nan=False).encode()).hexdigest()}
    try:
        required=_variables(candidate.expression)|_variables(reference.expression)
    except UnsupportedFragment as exc:
        return {**report,'status':'unsupported','reason':str(exc)}
    validate_domains(domains,scenario,required)
    try:
        z3=_load_z3()
    except ImportError:
        return {**report,'status':'unavailable','reason':'Install the optional z3-solver dependency'}
    report['solver_version']=z3.get_version_string()
    context=z3.Context()
    variables={name:z3.Real(name,ctx=context) for name in sorted(domains)}
    left=_lower(candidate.expression,variables,z3)
    right=_lower(reference.expression,variables,z3)
    solver=z3.SolverFor('QF_LRA',ctx=context)
    solver.set(timeout=timeout_ms)
    for name,bounds in domains.items():
        solver.add(variables[name]>=z3.RealVal(str(bounds['min']),ctx=context),
                   variables[name]<=z3.RealVal(str(bounds['max']),ctx=context))
    solver.add(z3.Xor(left,right))
    answer=solver.check()
    if answer==z3.unsat:
        return {**report,'status':'equivalent'}
    if answer!=z3.sat:
        return {**report,'status':'unknown','reason':solver.reason_unknown()}
    model=solver.model()
    exact={name:model.eval(var,model_completion=True).as_fraction() for name,var in variables.items()}
    values={name:float(value) for name,value in exact.items()}
    candidate_truth='SAFE' if z3.is_true(model.eval(left,model_completion=True)) else 'UNSAFE'
    reference_truth='SAFE' if z3.is_true(model.eval(right,model_completion=True)) else 'UNSAFE'
    replay_candidate=compile_rule(candidate,scenario).evaluate(values).value
    replay_reference=compile_rule(reference,scenario).evaluate(values).value
    replay_in_domain=all(Fraction(str(domains[name]['min']))<=Fraction(str(value))<=Fraction(str(domains[name]['max']))
                         for name,value in values.items())
    witness={'exact_values':{name:str(value) for name,value in exact.items()},
             'candidate':candidate_truth,'reference':reference_truth,
             'approximate_values':values,
             'float_replay_verified':replay_in_domain and replay_candidate==candidate_truth and replay_reference==reference_truth}
    return {**report,'status':'not_equivalent','counterexample':witness}
