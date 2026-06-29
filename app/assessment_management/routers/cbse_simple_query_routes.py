from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from uuid import UUID

from app.core.database import get_db
from ...auth_rbac.security.deps import get_current_principal
from ...auth_rbac.security.principal import Principal

router = APIRouter(prefix="/cbse-simple", tags=["CBSE Simple"])


@router.get("/content/{subject}")
async def get_cbse_content(
    subject: str,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),  # readable by any authed user, tenant-scoped
):
    """Get CBSE content using direct SQL queries (scoped to the principal's tenant)."""

    # Bind tenant to the principal; ignore the client value for non-super-admins.
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id

    # Get book chunks
    chunks_result = await db.execute(text("""
        SELECT id, chunk_title, content, key_concepts
        FROM book_chunks
        WHERE subject = :subject AND tenant_id = :tenant_id
    """), {"subject": subject, "tenant_id": str(effective_tenant)})

    chunks = [
        {
            "id": str(row[0]),
            "title": row[1],
            "content": row[2],
            "key_concepts": row[3]
        }
        for row in chunks_result.fetchall()
    ]

    # Get sample papers
    papers_result = await db.execute(text("""
        SELECT id, paper_title, paper_code, theory_marks
        FROM cbse_sample_papers
        WHERE subject = :subject AND tenant_id = :tenant_id
    """), {"subject": subject, "tenant_id": str(effective_tenant)})

    papers = [
        {
            "id": str(row[0]),
            "title": row[1],
            "code": row[2],
            "marks": row[3]
        }
        for row in papers_result.fetchall()
    ]

    return {
        "subject": subject,
        "book_chunks": chunks,
        "sample_papers": papers
    }
