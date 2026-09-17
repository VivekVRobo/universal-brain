from __future__ import annotations
from universal_brain.executive.providers.base import BaseModelProvider,ProviderMetadata,ProviderError
from universal_brain.executive.schemas import ExecutiveModelResponse
from universal_brain.kernel.events import ActionClass
from .schemas import TaskProfile,ModelCapability,SensitivityLevel
class IntelligenceFabricProvider(BaseModelProvider):
    """Compatibility projection so the existing ExecutiveScheduler can use the Fabric."""
    def __init__(self,fabric,context_compiler,route_hint=None):
        self.fabric=fabric;self.context_compiler=context_compiler;self.route_hint=route_hint
        super().__init__(ProviderMetadata(provider_id='intelligence-fabric',model_id='dynamic',model_family='multi-transport',context_window=1000000,cost_per_million_input=0,cost_per_million_output=0))
    async def generate_response(self,eap,tools=None):
        task=TaskProfile(task_id=eap.identity.task_id,task_kind='executive',required_context_tokens=4000,required_capabilities={ModelCapability.REASONING,ModelCapability.STRUCTURED_OUTPUT},sensitivity=SensitivityLevel.INTERNAL,action_class=ActionClass.A0,require_structured_output=True,metadata={'cognitive_role':'executive'})
        decision=self.fabric.router.select(task);route=self.fabric.runtime.catalog.require_route(decision.route_id);request=self.context_compiler.compile_eap(eap,task,route,tools)
        result=await self.fabric.invoke(task,request)
        data=result.structured_output
        if data is None:
            try:
                import json;data=json.loads(result.output_text)
            except Exception as exc:raise ProviderError('Intelligence Fabric result was not valid structured ExecutiveModelResponse JSON') from exc
        data=dict(data);data.setdefault('task_id',str(eap.identity.task_id));data.setdefault('lease_id',str(eap.identity.lease_id));data['raw_content']=result.output_text;data['provider_metadata']={'model_key':result.model_key,'route_id':result.route_id,'usage':result.usage.model_dump(mode='json')}
        return ExecutiveModelResponse.model_validate(data)
