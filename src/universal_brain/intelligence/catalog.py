from __future__ import annotations
from typing import Iterable
from .schemas import AccessRoute, ModelDescriptor
class CatalogError(ValueError): pass
class ModelCatalog:
    def __init__(self): self._models={}; self._routes={}
    def register_model(self,m:ModelDescriptor):
        if m.model_key in self._models: raise CatalogError(f'duplicate model {m.model_key}')
        self._models[m.model_key]=m
    def register_route(self,r:AccessRoute):
        if r.route_id in self._routes: raise CatalogError(f'duplicate route {r.route_id}')
        if r.model_key not in self._models: raise CatalogError(f'unknown model {r.model_key}')
        self._routes[r.route_id]=r
    def require_model(self,key:str)->ModelDescriptor:
        try:return self._models[key]
        except KeyError: raise CatalogError(f'unknown model {key}')
    def require_route(self,key:str)->AccessRoute:
        try:return self._routes[key]
        except KeyError: raise CatalogError(f'unknown route {key}')
    def list_routes(self,enabled_only=True): return [r for r in self._routes.values() if r.enabled or not enabled_only]
    def routes_for_model(self,key): return [r for r in self._routes.values() if r.model_key==key]
    def export(self): return {'models':[m.model_dump(mode='json') for m in self._models.values()],'routes':[r.model_dump(mode='json') for r in self._routes.values()]}
    @classmethod
    def from_items(cls,models:Iterable[ModelDescriptor],routes:Iterable[AccessRoute]):
        c=cls(); [c.register_model(x) for x in models]; [c.register_route(x) for x in routes]; return c
