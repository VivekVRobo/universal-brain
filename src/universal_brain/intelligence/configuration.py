import json
from pathlib import Path
from pydantic import BaseModel,Field,model_validator
from .catalog import ModelCatalog
from .schemas import ModelDescriptor,AccessRoute
class CatalogDocument(BaseModel):
    schema_version:int=Field(default=1,ge=1);models:list[ModelDescriptor]=Field(default_factory=list);routes:list[AccessRoute]=Field(default_factory=list)
    @model_validator(mode='after')
    def no_inline_secrets(self):
        forbidden={'api_key','apikey','access_token','refresh_token','password','passwd','authorization','cookie','cookies','private_key','client_secret','secret'}
        def walk(x,path='config'):
            if isinstance(x,dict):
                for k,v in x.items():
                    if str(k).lower() in forbidden and v not in (None,''):raise ValueError(f'inline credential prohibited at {path}.{k}')
                    walk(v,f'{path}.{k}')
            elif isinstance(x,list):
                for i,v in enumerate(x):walk(v,f'{path}[{i}]')
        for r in self.routes:walk(r.config,f'route[{r.route_id}]')
        return self
def load_catalog(path):
    d=CatalogDocument.model_validate(json.loads(Path(path).read_text(encoding='utf-8')));return ModelCatalog.from_items(d.models,d.routes)
def save_catalog(catalog,path):
    d=CatalogDocument.model_validate(catalog.export());Path(path).write_text(json.dumps(d.model_dump(mode='json'),indent=2,sort_keys=True)+'\n',encoding='utf-8')
