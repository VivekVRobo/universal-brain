from uuid import uuid4
import pytest
from universal_brain.executive.budget import BudgetGatekeeper
from universal_brain.intelligence import *
from universal_brain.intelligence.schemas import ModelMessage,ModelRequest,ModelUsage,NormalizedModelResult
from universal_brain.intelligence.transports.mock import MockTransport
from universal_brain.intelligence.transports.base import TransportRateLimitError
from universal_brain.kernel.events import ActionClass

def model(key,score=.9,context=128000):
    return ModelDescriptor(model_key=key,vendor='v',model_id=key,display_name=key,family='f',context_window=context,capability_profile=CapabilityProfile(scores={ModelCapability.REASONING:score,ModelCapability.CODING:score,ModelCapability.VERIFICATION:score}))
def catalog():
    c=ModelCatalog();c.register_model(model('frontier/a',.98,1000000));c.register_model(model('cheap/b',.75,256000));c.register_model(model('local/c',.7,128000))
    c.register_route(AccessRoute(route_id='a-api',model_key='frontier/a',transport=TransportKind.API,retention_policy=RetentionPolicy.ZERO_DATA_RETENTION,max_sensitivity=SensitivityLevel.CONFIDENTIAL,cost_per_million_input=10,cost_per_million_output=50))
    c.register_route(AccessRoute(route_id='a-browser',model_key='frontier/a',transport=TransportKind.BROWSER,retention_policy=RetentionPolicy.PROVIDER_DEFAULT,max_sensitivity=SensitivityLevel.INTERNAL))
    c.register_route(AccessRoute(route_id='b-api',model_key='cheap/b',transport=TransportKind.API,retention_policy=RetentionPolicy.PROVIDER_DEFAULT,max_sensitivity=SensitivityLevel.INTERNAL,cost_per_million_input=1,cost_per_million_output=2))
    c.register_route(AccessRoute(route_id='c-local',model_key='local/c',transport=TransportKind.LOCAL,retention_policy=RetentionPolicy.LOCAL_ONLY,max_sensitivity=SensitivityLevel.SECRET))
    return c

def test_model_identity_has_multiple_routes():
    assert {r.route_id for r in catalog().routes_for_model('frontier/a')}=={'a-api','a-browser'}

def test_secret_forced_local():
    r=IntelligenceRouter(catalog(),BudgetGatekeeper(monthly_budget_usd=100))
    d=r.select(TaskProfile(sensitivity=SensitivityLevel.SECRET,required_capabilities={ModelCapability.REASONING}))
    assert d.route_id=='c-local'

def test_router_no_vendor_branch_and_capability_fit():
    r=IntelligenceRouter(catalog(),BudgetGatekeeper(monthly_budget_usd=100))
    d=r.select(TaskProfile(required_capabilities={ModelCapability.CODING},minimum_capability_scores={ModelCapability.CODING:.9}))
    assert d.model_key=='frontier/a'

def test_budget_exhaustion_zero_cost_only():
    b=BudgetGatekeeper(monthly_budget_usd=1);b.cumulative_spend_usd=1
    d=IntelligenceRouter(catalog(),b).select(TaskProfile(required_capabilities={ModelCapability.REASONING}))
    assert catalog().require_route(d.route_id).cost_per_million_input==0

def test_quota_admission_moves_to_alternative():
    c=catalog();q=RouteQuotaRegistry();q.configure('a-api',RouteQuotaPolicy(max_requests=1));q.record_attempt('a-api')
    r=IntelligenceRouter(c,BudgetGatekeeper(monthly_budget_usd=100),quota_registry=q)
    d=r.select(TaskProfile(required_capabilities={ModelCapability.REASONING}))
    assert d.route_id!='a-api'
    assert any(x.route_id=='a-api' and 'quota' in x.reason.lower() for x in d.rejected)

@pytest.mark.asyncio
async def test_rate_limit_cooldown_is_route_scoped():
    c=catalog();q=RouteQuotaRegistry();q.configure('a-api',RouteQuotaPolicy(max_requests=10));mock=MockTransport();mock.rate_limit_routes.add('a-api')
    stack=build_intelligence_stack(c,budget=BudgetGatekeeper(monthly_budget_usd=100),quota=q,transports=[mock])
    d=stack.router.select(TaskProfile(required_capabilities={ModelCapability.CODING},allowed_transports={TransportKind.API},minimum_capability_scores={ModelCapability.CODING:.9}))
    with pytest.raises(TransportRateLimitError): await stack.runtime.invoke(d,ModelRequest(messages=[ModelMessage(role='user',content='x')]))
    d2=stack.router.select(TaskProfile(required_capabilities={ModelCapability.CODING},minimum_capability_scores={ModelCapability.CODING:.9}))
    assert d2.route_id=='a-browser'

def test_conversation_registry_atomic_persistence(tmp_path):
    path=tmp_path/'sessions.json';p=uuid4();r=ConversationRegistry(path);b=r.upsert(project_id=p,role='architect',model_key='frontier/a',route_id='a-api',conversation_ref='conv-1')
    r2=ConversationRegistry(path);loaded=r2.find(p,'architect','frontier/a','a-api')
    assert loaded and loaded.conversation_ref=='conv-1' and loaded.context_version==1
    r2.upsert(project_id=p,role='architect',model_key='frontier/a',route_id='a-api',conversation_ref='conv-2')
    assert ConversationRegistry(path).find(p,'architect').context_version==2

@pytest.mark.asyncio
async def test_fabric_tracks_conversation_continuity():
    c=catalog();mock=MockTransport();stack=build_intelligence_stack(c,budget=BudgetGatekeeper(monthly_budget_usd=100),transports=[mock]);p=uuid4()
    req=ModelRequest(messages=[ModelMessage(role='user',content='x')],metadata={'project_id':str(p),'cognitive_role':'architect'})
    out=await stack.fabric.invoke(TaskProfile(required_capabilities={ModelCapability.REASONING}),req)
    assert stack.conversations.find(p,'architect',out.model_key,out.route_id) is not None

@pytest.mark.asyncio
async def test_escalator_rejects_weak_result_then_uses_next_route():
    c=catalog();mock=MockTransport()
    stack=build_intelligence_stack(c,budget=BudgetGatekeeper(monthly_budget_usd=100),transports=[mock])
    task=TaskProfile(required_capabilities={ModelCapability.CODING},minimum_capability_scores={ModelCapability.CODING:.9})
    decision=stack.router.select(task)
    first=decision.selected_score.route_id; second=decision.alternatives[0].route_id
    mock.outputs[first]='x';mock.outputs[second]='this is long enough'
    req=ModelRequest(messages=[ModelMessage(role='user',content='x')],metadata={'min_output_chars':8})
    out=await stack.escalator.invoke(task,req)
    assert out.route_id==second
    assert len(out.raw_metadata['intelligence_escalation'])==2

def test_council_independent_critic_route():
    c=catalog();r=IntelligenceRouter(c,BudgetGatekeeper(monthly_budget_usd=100));planner=ModelCouncilPlanner(r)
    author=r.select(TaskProfile(required_capabilities={ModelCapability.REASONING}))
    a=planner.assign([CouncilRole(role='critic',task_profile=TaskProfile(required_capabilities={ModelCapability.VERIFICATION}),require_independent_route_from=author.route_id)])
    assert a.assignments['critic'].route_id!=author.route_id

@pytest.mark.asyncio
async def test_council_parallel_execution_marks_consensus_non_evidence():
    c=catalog();mock=MockTransport();stack=build_intelligence_stack(c,budget=BudgetGatekeeper(monthly_budget_usd=100),transports=[mock])
    roles=[CouncilRole(role='architect',task_profile=TaskProfile(required_capabilities={ModelCapability.REASONING})),CouncilRole(role='critic',task_profile=TaskProfile(required_capabilities={ModelCapability.VERIFICATION}))]
    reqs={r.role:ModelRequest(messages=[ModelMessage(role='user',content=r.role)]) for r in roles}
    out=await stack.council_executor.execute(roles,reqs)
    assert set(out)=={'architect','critic'}
    assert all(v.raw_metadata['council_consensus_is_evidence'] is False for v in out.values())

def test_catalog_rejects_inline_credentials(tmp_path):
    path=tmp_path/'bad.json';path.write_text('{"schema_version":1,"models":[],"routes":[]}',encoding='utf-8')
    from universal_brain.intelligence.configuration import CatalogDocument
    with pytest.raises(Exception):
        CatalogDocument.model_validate({'models':[model('x/y').model_dump(mode='json')],'routes':[AccessRoute(route_id='x-api',model_key='x/y',transport=TransportKind.API,config={'api_key':'secret'}).model_dump(mode='json')]})
