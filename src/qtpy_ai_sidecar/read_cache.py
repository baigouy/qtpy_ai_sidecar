"""A per-turn cache for explicitly read-only observations, never for edits."""
from collections import OrderedDict
import copy
import json

NOTICE='Already returned above; answer from it. Cached read-only result; no new tool execution.'

class TurnReadCache:
    def __init__(self,limit=64):
        self.limit=limit
        self.entries=OrderedDict()
        self.hits={}
    @staticmethod
    def key(tool_id,arguments,epoch=None):
        try:
            return (tool_id,json.dumps(arguments,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False),json.dumps(epoch,sort_keys=True,allow_nan=False))
        except (ValueError,TypeError):
            return None
    def lookup(self,key):
        if key is None or key not in self.entries:return None
        self.hits[key]=self.hits.get(key,0)+1
        result={'cache_notice':NOTICE,'cache_hit':True}
        result.update(copy.deepcopy(self.entries[key]))
        result['cache_notice']=NOTICE;result['cache_hit']=True
        return result
    @staticmethod
    def settled(result):
        # Do not freeze polling of queued GUI/background work.
        pending={'pending','queued','running','scheduled','in_progress','starting','loading','waiting'}
        def busy(value):
            if isinstance(value,dict):
                if any(str(value.get(k,'')).lower() in pending for k in ('status','state')):return True
                if any(value.get(k) is True for k in ('busy','pending','loading','pending_refresh')):return True
                return any(busy(v) for v in value.values() if isinstance(v,(dict,list)))
            if isinstance(value,list):return any(busy(v) for v in value)
            return False
        if busy(result):return False
        content=result.get('content')
        if isinstance(content,str):
            try:
                if busy(json.loads(content)):return False
            except (ValueError,TypeError):pass
        return True

    def remember(self,key,result):
        if key is None or not isinstance(result,dict) or not self.settled(result):return
        self.entries[key]=copy.deepcopy(result)
        self.hits[key]=0
        while len(self.entries)>self.limit:
            old,_=self.entries.popitem(last=False)
            self.hits.pop(old,None)
    def repeated(self,key):
        return key is not None and self.hits.get(key,0)>=2
    def invalidate(self):
        self.entries.clear()
        self.hits.clear()
