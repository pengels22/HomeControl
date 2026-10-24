from __future__ import annotations

import json
from importlib import import_module

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import db
from .auth import require_user
dashboard = import_module('05_PNL.dashboard')
DashboardError = dashboard.DashboardError
compile_dashboard = dashboard.compile_dashboard
validate_dashboard = dashboard.validate_dashboard

router = APIRouter(prefix='/api/v1/dashboard-editor', dependencies=[Depends(require_user)])


class DashboardCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
    scope: str = Field(default='shared', pattern=r'^(shared|panel|area)$')
    layout: dict


class LayoutUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    layout: dict
    expected_revision: int = Field(ge=0)


class RevisionAction(BaseModel):
    expected_revision: int = Field(ge=0)
    revision: int | None = Field(default=None, ge=1)


def _checked(layout):
    try:
        return compile_dashboard(layout)
    except DashboardError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('')
async def create_dashboard(body: DashboardCreate, user=Depends(require_user)):
    compiled = _checked(body.layout)
    async with db.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow('''INSERT INTO dashboard_documents(name,scope,owner,draft_revision)
                                         VALUES($1,$2,$3,1) RETURNING id''', body.name, body.scope, user['user'])
            await conn.execute('''INSERT INTO dashboard_revisions(dashboard_id,revision,layout,layout_sha256,created_by)
                                  VALUES($1,1,$2::jsonb,$3,$4)''', row['id'], json.dumps(compiled['layout']), compiled['sha256'], user['user'])
    return {'id': row['id'], 'revision': 1, 'sha256': compiled['sha256'], 'status': 'draft'}


@router.get('')
async def list_dashboards(user=Depends(require_user)):
    async with db.acquire() as conn:
        rows = await conn.fetch('''SELECT id,name,scope,owner,draft_revision,published_revision,updated_at
                                   FROM dashboard_documents ORDER BY name''')
    return {'dashboards': [dict(row) for row in rows]}


@router.put('/{dashboard_id}/draft')
async def update_draft(dashboard_id: int, body: LayoutUpdate, user=Depends(require_user)):
    compiled = _checked(body.layout)
    async with db.acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow('SELECT draft_revision FROM dashboard_documents WHERE id=$1 FOR UPDATE', dashboard_id)
            if not current:
                raise HTTPException(404, 'dashboard not found')
            if current['draft_revision'] != body.expected_revision:
                raise HTTPException(409, 'dashboard draft revision conflict')
            revision = body.expected_revision + 1
            await conn.execute('''INSERT INTO dashboard_revisions(dashboard_id,revision,layout,layout_sha256,created_by)
                                  VALUES($1,$2,$3::jsonb,$4,$5)''', dashboard_id, revision, json.dumps(compiled['layout']), compiled['sha256'], user['user'])
            await conn.execute('UPDATE dashboard_documents SET draft_revision=$2,updated_at=now() WHERE id=$1', dashboard_id, revision)
    return {'id': dashboard_id, 'revision': revision, 'sha256': compiled['sha256'], 'status': 'draft'}


@router.get('/{dashboard_id}/preview')
async def preview_dashboard(dashboard_id: int, user=Depends(require_user)):
    async with db.acquire() as conn:
        row = await conn.fetchrow('''SELECT d.draft_revision,r.layout,r.layout_sha256
                                     FROM dashboard_documents d JOIN dashboard_revisions r
                                       ON r.dashboard_id=d.id AND r.revision=d.draft_revision
                                     WHERE d.id=$1''', dashboard_id)
    if not row:
        raise HTTPException(404, 'dashboard not found')
    return {'preview_only': True, 'revision': row['draft_revision'], 'sha256': row['layout_sha256'], 'layout': row['layout']}


@router.post('/{dashboard_id}/publish')
async def publish_dashboard(dashboard_id: int, body: RevisionAction, user=Depends(require_user)):
    async with db.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow('SELECT draft_revision FROM dashboard_documents WHERE id=$1 FOR UPDATE', dashboard_id)
            if not row:
                raise HTTPException(404, 'dashboard not found')
            if row['draft_revision'] != body.expected_revision:
                raise HTTPException(409, 'dashboard publish conflict')
            await conn.execute('UPDATE dashboard_documents SET published_revision=$2,updated_at=now() WHERE id=$1', dashboard_id, body.expected_revision)
    return {'id': dashboard_id, 'published_revision': body.expected_revision, 'status': 'published'}


@router.post('/{dashboard_id}/revert')
async def revert_dashboard(dashboard_id: int, body: RevisionAction, user=Depends(require_user)):
    if body.revision is None:
        raise HTTPException(422, 'revision is required')
    async with db.acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow('SELECT draft_revision FROM dashboard_documents WHERE id=$1 FOR UPDATE', dashboard_id)
            target = await conn.fetchrow('SELECT layout FROM dashboard_revisions WHERE dashboard_id=$1 AND revision=$2', dashboard_id, body.revision)
            if not current or not target:
                raise HTTPException(404, 'dashboard or revision not found')
            if current['draft_revision'] != body.expected_revision:
                raise HTTPException(409, 'dashboard revert conflict')
            compiled = _checked(target['layout'])
            revision = body.expected_revision + 1
            await conn.execute('''INSERT INTO dashboard_revisions(dashboard_id,revision,layout,layout_sha256,created_by)
                                  VALUES($1,$2,$3::jsonb,$4,$5)''', dashboard_id, revision, json.dumps(compiled['layout']), compiled['sha256'], user['user'])
            await conn.execute('UPDATE dashboard_documents SET draft_revision=$2,updated_at=now() WHERE id=$1', dashboard_id, revision)
    return {'id': dashboard_id, 'revision': revision, 'reverted_from': body.revision}
