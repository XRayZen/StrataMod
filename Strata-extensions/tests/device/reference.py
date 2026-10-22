"""Independent byte oracle fixed before GPU execution."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];BUILD=ROOT/'build-deepseek-t21';HERE=Path(__file__).parent
def row(p):return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def prepare():
 c=json.loads((HERE/'contract.json').read_text(encoding='utf-8'));q=BUILD/'q';q.mkdir(exist_ok=True);p=q/'expected.bin';p.write_bytes(bytes((i*131+17+(i>>8)*7)&255 for i in range(c['region_bytes'])))
 d=dict(schema='T21-independent-byte-Q/v1',G_executed=False,contract=row(HERE/'contract.json'),reference=row(Path(__file__)),expected=row(p),lengths=c['lengths'],per_direction_payload=sum(c['lengths']),fixture_H2D_per_direction=sum(max(1,n) for n in c['lengths']),metadata='host ABI calibrated before G, not physical peak')
 (q/'manifest.json').write_text(json.dumps(d,indent=2)+'\n',encoding='utf-8');return d
