from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from uuid import UUID, uuid4
from fastapi.responses import Response

from app.core.database import get_db
from ...auth_rbac.security.deps import get_current_principal
from ...auth_rbac.access.deps import require_authority_or_module
from ...auth_rbac.security.principal import Principal

router = APIRouter(prefix="/cbse-pdf", tags=["CBSE PDF"])


@router.post("/upload-paper/{subject}")
async def upload_sample_paper(
    subject: str,
    tenant_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_authority_or_module('quizzes')),  # uploading study material: staff only
):
    """Upload PDF sample paper"""

    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files allowed")

    # Bind tenant to the principal; never trust the client tenant_id.
    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    if effective_tenant is None:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    pdf_content = await file.read()
    paper_id = str(uuid4())

    await db.execute(text("""
        INSERT INTO cbse_sample_papers
        (id, tenant_id, subject, paper_title, paper_code, pdf_content, pdf_filename, pdf_size, created_at, is_deleted)
        VALUES (:id, :tenant_id, :subject, :title, :code, :pdf_content, :filename, :size, NOW(), false)
    """), {
        "id": paper_id,
        "tenant_id": str(effective_tenant),
        "subject": subject,
        "title": f"{subject.replace('_', ' ').title()} Sample Paper",
        "code": subject.split('_')[-1],
        "pdf_content": pdf_content,
        "filename": file.filename,
        "size": len(pdf_content)
    })

    await db.commit()

    return {
        "message": "PDF uploaded successfully",
        "paper_id": paper_id,
        "filename": file.filename,
        "size": len(pdf_content)
    }


@router.get("/download-paper/{paper_id}")
async def download_sample_paper(
    paper_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),  # students may read study material
):
    """Download PDF sample paper (tenant-scoped — no cross-tenant IDOR)."""

    if principal.is_super_admin:
        result = await db.execute(text("""
            SELECT pdf_content, pdf_filename FROM cbse_sample_papers
            WHERE id = :paper_id AND pdf_content IS NOT NULL AND is_deleted = false
        """), {"paper_id": str(paper_id)})
    else:
        result = await db.execute(text("""
            SELECT pdf_content, pdf_filename FROM cbse_sample_papers
            WHERE id = :paper_id AND tenant_id = :tenant_id AND pdf_content IS NOT NULL AND is_deleted = false
        """), {"paper_id": str(paper_id), "tenant_id": str(principal.tenant_id)})

    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="PDF not found")

    return Response(
        content=row[0],
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={row[1]}"}
    )


@router.get("/papers/{subject}")
async def list_pdf_papers(
    subject: str,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """List PDF papers for a subject (tenant-scoped to the principal)."""

    effective_tenant = tenant_id if principal.is_super_admin else principal.tenant_id
    result = await db.execute(text("""
        SELECT id, paper_title, pdf_filename, pdf_size, created_at
        FROM cbse_sample_papers
        WHERE subject = :subject AND tenant_id = :tenant_id AND pdf_content IS NOT NULL AND is_deleted = false
    """), {"subject": subject, "tenant_id": str(effective_tenant)})

    papers = [
        {
            "id": str(row[0]),
            "title": row[1],
            "filename": row[2],
            "size": row[3],
            "uploaded_at": row[4].isoformat() if row[4] else None
        }
        for row in result.fetchall()
    ]

    return {"subject": subject, "papers": papers}
