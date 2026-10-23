"""Verified source images, including independently loaded sections of a disc container."""
import copy
import hashlib
import re


def expand_modules(profile, manifest):
    modules = copy.deepcopy(profile['modules'])
    for container in profile.get('module_containers', []):
        source = container['file']
        prefix = container['prefix']
        if not re.fullmatch(r'[A-Za-z0-9_]+\.BIN', source) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', prefix):
            raise ValueError('Unsafe container name')
        stride = int(container['chunk_bytes'], 16)
        count = container['count']
        if not isinstance(count, int) or count < 1 or count > 256 or stride < 12 or stride & 3:
            raise ValueError('Invalid container layout')
        if manifest['files']['/'+source]['size'] != stride * count:
            raise ValueError('Container size does not match its verified layout: '+source)
        base = int(container['base'], 16)
        if base < 0 or base & 1 or base+stride > 0x100000000:
            raise ValueError('Invalid container load address')
        for index in range(count):
            name = prefix + f'{index:02X}'
            module = dict(name=name, file=name+'.BIN', source_file=source,
                          offset=f'{stride*index:X}', bytes=f'{stride:X}', base=f'{base:08X}',
                          required_veneer_offsets=list(container['entry_offsets']),
                          seeds=[f'{base+offset:08X}' for offset in container['entry_offsets']],
                          overlay=True, evidence=container['evidence'])
            if any(offset < 0 or offset & 1 or offset >= stride for offset in container['entry_offsets']):
                raise ValueError('Container entry is outside its image')
            existing = [m for m in modules if m['name']==name or m['file']==module['file']]
            if existing:
                if len(existing)!=1 or any(existing[0].get(k)!=v for k,v in module.items() if k not in ('seeds','evidence')) or not set(module['seeds'])<=set(existing[0]['seeds']):
                    raise ValueError('Container module collides with an existing image: '+name)
            else:
                modules.append(module)
    return modules


def verified_source(work, module, manifest):
    name = module.get('source_file', module['file'])
    if not re.fullmatch(r'[A-Za-z0-9_]+\.BIN', name):
        raise ValueError('Unsafe module source filename')
    path = work/'extract'/name
    data = path.read_bytes()
    expected = manifest['files']['/'+name]
    if len(data)!=expected['size'] or hashlib.sha1(data).hexdigest()!=expected['sha1']:
        raise ValueError('Extracted module changed: '+name)
    return path, data


def image_bytes(module, original):
    offset = int(module.get('offset','0'),16)
    count = int(module['bytes'],16) if 'bytes' in module else len(original)
    if offset < 0 or count < 1 or offset > len(original)-count:
        raise ValueError('Module image extends outside its verified source: '+module['file'])
    if 'source_file' in module and ('offset' not in module or 'bytes' not in module):
        raise ValueError('Container module needs an exact offset and length')
    data = original[offset:offset+count]
    base = int(module['base'],16)
    if base < 0 or base & 1 or base+count > 0x100000000:
        raise ValueError('Invalid module load address: '+module['file'])
    for seed in module.get('seeds', []):
        entry = int(seed,16)
        if entry & 1 or not base <= entry <= base+count-2:
            raise ValueError('Module entry is outside its image or unaligned: '+module['file'])
    for pc in module.get('stack_return_calls', []):
        at = int(pc,16)-base
        if at & 1 or at < 2 or at+6 > len(data) or data[at-2:at+2] != bytes.fromhex('4f22400b') or data[at+4:at+6] != bytes.fromhex('4f26'):
            raise ValueError('Stack-return call must have its verified PR-save/call/restore wrapper: '+module['file'])
    for at in module.get('required_veneer_offsets', []):
        if at < 0 or at+12>len(data) or data[at:at+8] != bytes.fromhex('d001402b00090009'):
            raise ValueError('Container export header is invalid: '+module['file'])
        target = int.from_bytes(data[at+8:at+12],'big')
        if target & 1 or not base <= target <= base+len(data)-2:
            raise ValueError('Container export points outside its image: '+module['file'])
    return data
