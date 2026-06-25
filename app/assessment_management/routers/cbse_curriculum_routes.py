from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any
from uuid import UUID

from ...core.database import get_db
from ...assessment_management.services.cbse_curriculum_service import CBSEContentService
from ...auth_rbac.security.deps import get_current_principal, require_staff
from ...auth_rbac.security.principal import Principal

router = APIRouter(prefix="/cbse", tags=["CBSE Content"])


def _tenant(principal: Principal, tenant_id: UUID) -> UUID:
    """Bind tenant to the principal; ignore the client value for non-super-admins."""
    return tenant_id if principal.is_super_admin else principal.tenant_id


@router.post("/generate-chunks/{subject}")
async def generate_book_chunks(
    subject: str,
    chapter_content: str,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),  # AI content authoring: staff only
):
    """Generate AI-powered book chunks for a subject"""
    service = CBSEContentService(db)

    try:
        chunks = await service.generate_book_chunks(subject, chapter_content, _tenant(principal, tenant_id))
        return {
            "message": f"Generated {len(chunks)} chunks for {subject}",
            "chunks": [{"id": str(c.id), "title": c.chunk_title} for c in chunks]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-sample-paper/{subject}")
async def generate_sample_paper(
    subject: str,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),  # AI content authoring: staff only
):
    """Generate CBSE pattern sample paper"""
    service = CBSEContentService(db)

    try:
        paper = await service.generate_sample_paper(subject, _tenant(principal, tenant_id))
        return {
            "message": f"Generated sample paper for {subject}",
            "paper": {
                "id": str(paper.id),
                "title": paper.paper_title,
                "code": paper.paper_code,
                "marks": paper.theory_marks
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/content/{subject}")
async def get_subject_content(
    subject: str,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),  # readable by any authed user, tenant-scoped
) -> Dict[str, Any]:
    """Get all content for a subject (scoped to the principal's tenant)."""
    service = CBSEContentService(db)

    try:
        content = await service.get_subject_content(subject, _tenant(principal, tenant_id))
        return content
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bulk-generate")
async def bulk_generate_content(
    tenant_id: UUID,
    subjects: List[str],
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),  # AI content authoring: staff only
):
    """Generate sample papers for multiple subjects"""
    service = CBSEContentService(db)
    results = []
    effective_tenant = _tenant(principal, tenant_id)

    for subject in subjects:
        try:
            paper = await service.generate_sample_paper(subject, effective_tenant)
            results.append({
                "subject": subject,
                "status": "success",
                "paper_id": str(paper.id)
            })
        except Exception as e:
            results.append({
                "subject": subject,
                "status": "error",
                "error": str(e)
            })

    return {"results": results}
