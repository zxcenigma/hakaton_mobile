import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from monoapi.apps.fastapi import api
from monoapi.db.models import DiaryModel, TargetModel, UserModel

pytestmark = pytest.mark.asyncio
PREFIX = "/api/v1/diary"
TARGETS_PREFIX = "/api/v1/targets"


def query(db, **kwargs):
    return dict(user_uuid=db[1][0], **kwargs)


async def target(client, db, amount=1000, **kwargs):
    response = await client.post(TARGETS_PREFIX, params=query(db),
                                 json=dict(name=" Цель ", target_count=amount, **kwargs))
    assert response.status_code == 201, response.text
    return response.json()


async def operation(client, db, kind="investment", amount=100, day="2026-09-29", **kwargs):
    response = await client.post(PREFIX + "/operations", params=query(db),
                                 json=dict(name=" Покупка ", amount=amount, operation_type=kind,
                                           operation_date=day, **kwargs))
    assert response.status_code == 201, response.text
    return response.json()


async def goal(client, db, uuid):
    response = await client.get(TARGETS_PREFIX + "/" + uuid, params=query(db))
    assert response.status_code == 200, response.text
    return response.json()


async def test_investment_full_lifecycle(client, db):
    first, second = await target(client, db), await target(client, db, 300)
    assert first['name'] == 'Цель' and first['current_count'] == 0 and Decimal(first['percentage']) == 0
    op = await operation(client, db, target_uuid=first['uuid'], category='Супермаркеты')
    assert op['name'] == 'Покупка'
    assert (await goal(client, db, first['uuid']))['current_count'] == 100
    path = PREFIX + '/operations/' + op['uuid']
    response = await client.patch(path, params=query(db), json={'amount': 200})
    assert response.status_code == 200
    assert Decimal((await goal(client, db, first['uuid']))['percentage']) == 20
    response = await client.patch(path, params=query(db), json={'target_uuid': second['uuid']})
    assert response.status_code == 200
    assert (await goal(client, db, first['uuid']))['current_count'] == 0
    assert Decimal((await goal(client, db, second['uuid']))['percentage']) == Decimal('66.67')
    response = await client.patch(path, params=query(db), json={'target_uuid': None, 'category': None})
    assert response.status_code == 200 and response.json()['category'] is None
    assert (await goal(client, db, second['uuid']))['current_count'] == 0
    await client.patch(path, params=query(db), json={'target_uuid': second['uuid'], 'amount': 400})
    assert Decimal((await goal(client, db, second['uuid']))['percentage']) == 100
    response = await client.patch(path, params=query(db), json={'operation_type': 'expense'})
    assert response.status_code == 200 and response.json()['target_uuid'] is None
    assert (await goal(client, db, second['uuid']))['current_count'] == 0
    await client.patch(path, params=query(db), json={'operation_type': 'investment', 'target_uuid': first['uuid']})
    response = await client.delete(path, params=query(db))
    assert response.status_code == 204 and response.content == b''
    assert (await goal(client, db, first['uuid']))['current_count'] == 0
    assert (await client.delete(path, params=query(db))).status_code == 404


async def test_edit_and_delete_target_preserve_diary(client, db):
    item = await target(client, db, description='Описание')
    op = await operation(client, db, target_uuid=item['uuid'])
    path = TARGETS_PREFIX + "/" + item['uuid']
    response = await client.patch(path, params=query(db), json={'name': 'Новое', 'description': None, 'target_count': 200})
    assert response.status_code == 200
    assert response.json()['description'] is None and response.json()['name'] == 'Новое'
    assert Decimal(response.json()['percentage']) == 50
    response = await client.delete(path, params=query(db))
    assert response.status_code == 204 and not response.content
    assert (await client.get(path, params=query(db))).status_code == 404
    week = (await client.get(PREFIX+'/week', params=query(db, anchor_date='2026-09-29'))).json()
    remaining = [operation for day in week['days'] for operation in day['operations']]
    assert len(remaining) == 1 and remaining[0]['uuid'] == op['uuid']
    assert remaining[0]['target_uuid'] is None and remaining[0]['amount'] == 100
    counts = (await client.get(PREFIX+'/counts/year', params=query(db, year=2026))).json()
    assert counts['investment_total'] == 100


async def test_calendar_ranges_and_user_isolation(client, db):
    for kind, amount, day in [('income',1000,'2024-02-26'),('expense',100,'2024-02-29'),
                              ('investment',200,'2024-03-03'),('income',999,'2024-03-04'),
                              ('income',50,'2023-12-31')]:
        await operation(client, db, kind, amount, day)
    response = await client.get(PREFIX+'/week', params=query(db, anchor_date='2024-03-01'))
    assert response.status_code == 200, response.text
    week = response.json()
    assert week['week_start'] == '2024-02-26' and week['week_end'] == '2024-03-03'
    assert week['display_month'] == 3 and week['display_year'] == 2024
    assert len(week['days']) == 7 and week['days'][1]['operations'] == []
    assert week['days'][1]['net_total'] == 0
    for period, params, expected in [
        ('week', {'anchor_date':'2024-03-01'}, (1000,100,200,700)),
        ('month', {'year':2024,'month':2}, (1000,100,0,900)),
        ('year', {'year':2024}, (1999,100,200,1699)),
        ('week', {'anchor_date':'2023-12-31'}, (50,0,0,50)),
        ('year', {'year':2025}, (0,0,0,0)),
    ]:
        result = await client.get(PREFIX+'/counts/'+period, params=query(db, **params))
        assert result.status_code == 200, result.text
        assert tuple(result.json()[field] for field in ['income_total','expense_total','investment_total','net_total']) == expected
    other = (await client.get(PREFIX+'/week', params={'user_uuid':db[1][1], 'anchor_date':'2024-03-01'})).json()
    assert all(not day['operations'] for day in other['days'])
    feb = (await client.get(PREFIX+'/counts/month', params=query(db, year=2024, month=2))).json()
    assert feb['period_end_exclusive'] == '2024-03-01'
    december = (await client.get(PREFIX+'/counts/month', params=query(db, year=2024, month=12))).json()
    assert december['period_end_exclusive'] == '2025-01-01'
    cross = (await client.get(PREFIX+'/week', params=query(db, anchor_date='2025-01-01'))).json()
    assert cross['week_start'] == '2024-12-30' and cross['week_end'] == '2025-01-05'


@pytest.mark.parametrize('changes', [
    {'amount':0}, {'amount':-1}, {'amount':1.5}, {'amount':True}, {'amount':2147483648},
    {'name':'  '}, {'name':'x'*201}, {'operation_type':'invalid'}, {'category':'invalid'},
    {'operation_date':'2024-02-30'}, {'operation_date':'9999-12-31'},
    {'operation_type':'expense','target_uuid':str(uuid4())}, {'user_id':123},
])
async def test_invalid_create(client, db, changes):
    body=dict(name='Операция',amount=10,operation_type='income',operation_date='2026-09-29')
    body.update(changes)
    response = await client.post(PREFIX+'/operations', params=query(db), json=body)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize('changes', [{}, {'name':None}, {'amount':None}, {'operation_date':None}, {'operation_type':None}, {'user_id':1}])
async def test_invalid_operation_patch(client, db, changes):
    item=await operation(client, db)
    response=await client.patch(PREFIX+'/operations/'+item['uuid'], params=query(db), json=changes)
    assert response.status_code == 422


@pytest.mark.parametrize('changes', [{}, {'name':None}, {'name':' '}, {'target_count':None}, {'target_count':0}, {'target_count':1.5}, {'current_count':10}, {'percentage':50}])
async def test_invalid_target_patch(client, db, changes):
    item=await target(client, db)
    response=await client.patch(TARGETS_PREFIX + "/"+item['uuid'], params=query(db), json=changes)
    assert response.status_code == 422


@pytest.mark.parametrize('changes', [{'target_count':0}, {'target_count':1.2}, {'name':' '}, {'current_count':1}, {'percentage':2}])
async def test_invalid_target_create(client, db, changes):
    body={'name':'Цель','target_count':100};body.update(changes)
    assert (await client.post(TARGETS_PREFIX, params=query(db), json=body)).status_code == 422


async def test_missing_and_foreign_resources(client, db):
    item=await target(client, db)
    op=await operation(client, db)
    other={'user_uuid':db[1][1]}
    for method, path, body in [
        ('get','/targets/'+item['uuid'],None),('patch','/targets/'+item['uuid'],{'name':'X'}),
        ('delete','/targets/'+item['uuid'],None),('patch','/operations/'+op['uuid'],{'name':'X'}),
        ('delete','/operations/'+op['uuid'],None),
        ('post','/operations',{'name':'X','operation_date':'2026-09-29','operation_type':'investment','amount':1,'target_uuid':item['uuid']}),
    ]:
        url = "/api/v1" + path if path.startswith("/targets/") else PREFIX + path
        response=await client.request(method,url,params=other,**({'json':body} if body else {}))
        assert response.status_code == 404, response.text
    assert (await client.get(PREFIX+'/week',params={'user_uuid':str(uuid4()),'anchor_date':'2026-01-01'})).status_code == 404
    assert (await client.get(TARGETS_PREFIX + "/"+str(uuid4()),params=query(db))).status_code == 404
    assert (await client.get(PREFIX+'/week',params={'anchor_date':'2026-01-01'})).status_code == 422


async def test_failed_update_is_atomic(client, db, monkeypatch):
    from monoapi.routers.services.diary.calendar import update_diary_operation as module
    first, second=await target(client,db),await target(client,db)
    op=await operation(client,db,target_uuid=first['uuid'])
    original=module.apply_target_delta
    calls=0
    async def fail_on_second(*args):
        nonlocal calls
        calls+=1
        await original(*args)
        if calls == 2:
            raise RuntimeError('Simulated transaction failure')
    monkeypatch.setattr(module,'apply_target_delta',fail_on_second)
    with pytest.raises(RuntimeError,match='Simulated'):
        await client.patch(PREFIX+'/operations/'+op['uuid'],params=query(db),json={'target_uuid':second['uuid'],'amount':300})
    assert (await goal(client,db,first['uuid']))['current_count'] == 100
    assert (await goal(client,db,second['uuid']))['current_count'] == 0
    week=(await client.get(PREFIX+'/week',params=query(db,anchor_date='2026-09-29'))).json()
    saved=week['days'][1]['operations'][0]
    assert saved['amount'] == 100 and saved['target_uuid'] == first['uuid']


async def test_concurrent_investments_and_edits(client,db):
    item=await target(client,db,10000)
    ops=await asyncio.gather(*[operation(client,db,amount=10,target_uuid=item['uuid']) for _ in range(12)])
    assert (await goal(client,db,item['uuid']))['current_count'] == 120
    path=PREFIX+'/operations/'+ops[0]['uuid']
    responses=await asyncio.gather(*[client.patch(path,params=query(db),json={'amount':amount}) for amount in range(20,30)])
    assert all(r.status_code==200 for r in responses)
    async with db[0].session() as session:
        row=await session.scalar(select(TargetModel).where(TargetModel.uuid==item['uuid']))
        total=await session.scalar(select(func.sum(DiaryModel.amount)).where(DiaryModel.target_id==row.id))
        assert row.current_count == total
    # Target deletion and a new investment serialize; either creation precedes
    # deletion or receives 404. Both results leave a valid unlinked diary.
    results=await asyncio.gather(
        client.delete(TARGETS_PREFIX + "/"+item['uuid'],params=query(db)),
        client.post(PREFIX+'/operations',params=query(db),json=dict(name='Race',operation_date='2026-09-29',operation_type='investment',amount=1,target_uuid=item['uuid'])),
    )
    assert results[0].status_code==204 and results[1].status_code in (201,404)
    async with db[0].session() as session:
        assert await session.scalar(select(func.count()).select_from(DiaryModel).where(DiaryModel.target_id==row.id)) == 0


async def test_stable_sort_balance_and_opening_savings(client,db):
    item=await target(client,db)
    async with db[0].session() as session:
        model=await session.scalar(select(TargetModel).where(TargetModel.uuid==item['uuid']))
        model.current_count=50
        model.percentage=Decimal('5.00')
        await session.commit()
    first=await operation(client,db,target_uuid=item['uuid'])
    second=await operation(client,db,kind='expense')
    async with db[0].session() as session:
        entries=(await session.scalars(select(DiaryModel).where(DiaryModel.uuid.in_([first['uuid'],second['uuid']])))).all()
        for entry in entries:
            entry.created_at=datetime(2026,1,1,tzinfo=timezone.utc)
        await session.commit()
        user=await session.scalar(select(UserModel).where(UserModel.uuid==db[1][0]))
        assert user.balance==0
    week=(await client.get(PREFIX+'/week',params=query(db,anchor_date='2026-09-29'))).json()
    assert [x['uuid'] for x in week['days'][1]['operations']] == [first['uuid'],second['uuid']]
    assert (await goal(client,db,item['uuid']))['current_count']==150
    await client.delete(PREFIX+'/operations/'+first['uuid'],params=query(db))
    assert (await goal(client,db,item['uuid']))['current_count']==50


async def test_openapi_and_invalid_query(client,db):
    schema=api.openapi()
    methods=[]
    for path,routes in schema['paths'].items():
        if path.startswith(PREFIX+'/') or path == TARGETS_PREFIX or path.startswith(TARGETS_PREFIX+'/'):
            for operation in routes.values():
                methods.append(operation)
                expected_tag = 'targets' if path.startswith(TARGETS_PREFIX) else 'diary'
                assert operation['tags'] == [expected_tag]
                assert not operation.get('security')
                assert any(p['name']=='user_uuid' and p['in']=='query' and p['required'] for p in operation['parameters'])
    assert len(methods)==11
    assert sum(operation['tags'] == ['targets'] for operation in methods) == 4
    assert sum(operation['tags'] == ['diary'] for operation in methods) == 7
    assert PREFIX + '/targets' not in schema['paths']
    assert PREFIX + '/targets/{target_uuid}' not in schema['paths']
    assert (await client.post(PREFIX+'/targets', params=query(db), json={'name':'Old URL','target_count':100})).status_code == 404
    for path,params in [('/counts/month',{'year':2024,'month':13}),('/counts/year',{'year':9999}),('/week',{'anchor_date':'bad'})]:
        assert (await client.get(PREFIX+path,params=query(db,**params))).status_code==422
