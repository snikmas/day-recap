"""Record desktop-reported execution evidence without guessing availability."""

HISTORY_TOOLS = {'list_threads', 'read_thread', 'list_archived_threads'}


def snapshot(cfg, evidence=None):
    preference = cfg.get('model_preference', {'policy': 'inherit'})
    requested = {'policy': preference.get('policy', 'inherit'),
                 'model': preference.get('model'), 'reasoning': preference.get('reasoning')}
    evidence = {} if evidence is None else evidence
    if not isinstance(evidence, dict):
        raise ValueError('Desktop evidence must be a JSON object.')
    for name in ('model', 'reasoning', 'host', 'model_source', 'catalog_source'):
        if evidence.get(name) is not None and not isinstance(evidence[name], str):
            raise ValueError('Desktop evidence field ' + name + ' must be text or null.')
    if (not isinstance(evidence.get('history_tools', []), list)
            or any(not isinstance(name, str) for name in evidence.get('history_tools', []))):
        raise ValueError('History tool evidence must be a list of tool names.')
    if evidence.get('available_models') is not None:
        if (not isinstance(evidence['available_models'], list)
                or any(not isinstance(name, str) for name in evidence['available_models'])):
            raise ValueError('Desktop model catalog must be a list of model names.')
    observed = {name: evidence.get(name) or 'unknown'
                for name in ('model', 'reasoning', 'host')}
    # Only a reported host capability establishes a model catalog. A cached
    # name or a separate CLI invocation does not establish desktop availability.
    catalog = evidence.get('available_models') if evidence.get('catalog_source') == 'host' else None
    tools = set(evidence.get('history_tools', []))
    missing = sorted(HISTORY_TOOLS - tools) if 'chatgpt' in cfg.get('sources', []) else []
    pending = []
    if requested['policy'] == 'specific':
        if catalog is not None and (not isinstance(catalog, list) or requested['model'] not in catalog):
            pending.append('Requested model is unavailable in the reported desktop catalog.')
        elif catalog is None and not (evidence.get('model_source') == 'host'
                                      and observed['model'] == requested['model']
                                      and observed['host'] != 'unknown'):
            pending.append('Requested model availability must be checked in desktop.')
        if observed['model'] != requested['model']:
            pending.append('Switch the desktop chat to the requested model, then resume.')
        if requested['reasoning'] and observed['reasoning'] != requested['reasoning']:
            pending.append('Select the requested reasoning setting in desktop, then resume.')
    if missing:
        pending.append('Required desktop history tools are unverified: ' + ', '.join(missing))
    return {'requested': requested, 'observed': observed,
            'evidence_source': 'desktop-reported' if evidence else 'unknown',
            'history_tools': sorted(tools), 'pending': pending}


def require_ready(cfg, evidence=None):
    details = snapshot(cfg, evidence)
    if details['pending']:
        raise RuntimeError('Run remains pending. ' + ' '.join(details['pending']))
    return details
