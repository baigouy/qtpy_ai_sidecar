"""Native mirror flags preserve source pixels; legacy scripts replace them."""
import importlib.util
from pathlib import Path
import pytest
path=Path(__file__).resolve().parents[1]/'validation/pyfigures/checks.py'
spec=importlib.util.spec_from_file_location('native_flip_checks',path)
checks=importlib.util.module_from_spec(spec);spec.loader.exec_module(checks)

@pytest.mark.parametrize('axis',['h','v'])
@pytest.mark.parametrize('flag,pixels,passes',[
    (True,'source',True),
    (False,'source',False),
    (False,'mirrored',True),
    (True,'unrelated',False),
])
def test_native_and_legacy_flip_paths(axis,flag,pixels,passes):
    panel={'panel_id':'0/2','letters':[{'text':'c'}]}
    before={'letters':{'panels':[panel]},'images':[{'panel_id':'0/2','pixel_digest':'source','flip_'+axis+'_digest':'mirrored'}]}
    after={'letters':{'panels':[panel]},'images':[{'panel_id':'0/2','pixel_digest':pixels,'flip_'+axis:flag}]}
    failures=checks.verify({'flip_'+axis:'c'},before,after,[],[])
    assert ('Displayed pixels were not flipped '+axis not in failures)==passes

@pytest.mark.parametrize('axis',['h','v'])
def test_native_flag_without_known_source_pixels_is_not_success(axis):
    panel={'panel_id':'0/2','letters':[{'text':'c'}]}
    before={'letters':{'panels':[panel]},'images':[{'panel_id':'0/2'}]}
    after={'letters':{'panels':[panel]},'images':[{'panel_id':'0/2','flip_'+axis:True}]}
    assert 'Displayed pixels were not flipped '+axis in checks.verify({'flip_'+axis:'c'},before,after,[],[])
