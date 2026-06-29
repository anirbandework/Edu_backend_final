# app/services/organisation_service.py
from typing import List, Optional, Dict, Any
from uuid import UUID
import uuid
from datetime import datetime, timezone, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func, update, and_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert
from fastapi import HTTPException
import logging
from ...services.base_service import BaseService
from ..models.organisation import Organisation

logger = logging.getLogger(__name__)

class OrganisationService(BaseService[Organisation]):
    # Required fields for organisation validation
    REQUIRED_ORGANISATION_FIELDS = [
        "name", "address", "phone", "email", "head_name", 
        "annual_tuition", "registration_fee", "maximum_capacity", "levels_offered"
    ]
    
    def __init__(self, db: AsyncSession):
        super().__init__(Organisation, db)
    

    
    async def create(self, obj_in: dict) -> Organisation:
        """Create organisation"""
        return await super().create(obj_in)
    
    async def get_by_code(self, code: str) -> Optional[Organisation]:
        """Get organisation by organisation code (format: ABC2024001)"""
        if not code or not code.strip():
            raise HTTPException(status_code=400, detail="Organisation code cannot be empty")
        
        try:
            stmt = select(self.model).where(
                and_(
                    self.model.code == code.strip().upper(),
                    self.model.is_deleted.is_(False)
                )
            )
            result = await self.db.execute(stmt)
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            # Sanitize inputs to prevent code injection
            sanitized_code = str(code).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:50]
            sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
            logger.error("Error getting organisation by organisation code '%s': %s", sanitized_code, sanitized_error)
            raise HTTPException(status_code=500, detail="Database error occurred while fetching organisation")
    
    async def get_by_email(self, email: str) -> Optional[Organisation]:
        """Get organisation by email address"""
        if not email or not email.strip():
            raise HTTPException(status_code=400, detail="Email cannot be empty")
        
        try:
            stmt = select(self.model).where(
                and_(
                    self.model.email == email.strip().lower(),
                    self.model.is_deleted.is_(False)
                )
            )
            result = await self.db.execute(stmt)
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            # Sanitize email for logging to prevent code injection
            sanitized_email = str(email).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:100]
            sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
            logger.error("Error getting organisation by email '%s': %s", sanitized_email, sanitized_error)
            raise HTTPException(status_code=500, detail="Database error occurred while fetching organisation")
    
    async def get_organisation_charges(self, organisation_id: UUID) -> dict:
        """Get charge details for a specific organisation"""
        try:
            stmt = select(
                self.model.id,
                self.model.name,
                self.model.charges_applied,
                self.model.charges_amount
            ).where(
                and_(
                    self.model.id == organisation_id,
                    self.model.is_deleted.is_(False)
                )
            )
            result = await self.db.execute(stmt)
            organisation = result.fetchone()
            
            if not organisation:
                raise HTTPException(status_code=404, detail="Organisation not found")
            
            return {
                "organisation_id": str(organisation.id),
                "name": organisation.name,
                "charges_applied": organisation.charges_applied,
                "charges_amount": float(organisation.charges_amount) if organisation.charges_amount else None
            }
        except HTTPException:
            raise
        except SQLAlchemyError as e:
            logger.error("Database error getting organisation charges %s: %s", organisation_id, str(e))
            raise HTTPException(status_code=500, detail="Database error occurred while fetching charges")
        except Exception as e:
            logger.error("Unexpected error getting organisation charges %s: %s", organisation_id, str(e))
            raise HTTPException(status_code=500, detail="An unexpected error occurred")
    
    async def get_active_organisations(self, limit: Optional[int] = None) -> List[Organisation]:
        """Get all active organisations with optional limit for performance"""
        try:
            # Validate database connection
            if not self.db:
                raise HTTPException(status_code=500, detail="Database connection not available")
            
            stmt = select(self.model).where(
                and_(
                    self.model.is_active.is_(True),
                    self.model.is_deleted.is_(False)
                )
            ).order_by(self.model.name)
            
            # Apply limit if specified to prevent memory issues
            if limit and limit > 0:
                stmt = stmt.limit(limit)
            
            result = await self.db.execute(stmt)
            organisations = result.scalars().all()
            
            # Convert to list safely
            return list(organisations) if organisations else []
            
        except SQLAlchemyError as e:
            logger.error("Database error getting active organisations: %s", e)
            raise HTTPException(
                status_code=500, 
                detail="Database error occurred while fetching active organisations"
            )
        except ValueError as e:
            logger.error("Value error getting active organisations: %s", e)
            raise HTTPException(
                status_code=400, 
                detail="Invalid parameters provided"
            )
        except Exception as e:
            logger.error("Unexpected error getting active organisations: %s", e)
            raise HTTPException(
                status_code=500, 
                detail="An unexpected error occurred while fetching active organisations"
            )
    
    async def generate_code(self, name: str) -> str:
        """Generate unique organisation code in format: ABC2024001"""
        try:
            if not name or not name.strip():
                raise HTTPException(status_code=400, detail="Organisation name cannot be empty")
            
            # Validate database connection
            if not self.db:
                raise HTTPException(status_code=500, detail="Database connection not available")
            
            current_year = datetime.now(timezone.utc).year
            
            # Extract alphabetic characters and create 3-letter prefix
            PREFIX_LENGTH = 3
            PADDING_CHAR = 'X'
            
            # Get only alphabetic characters from organisation name
            alphabetic_chars = [c.upper() for c in name if c.isalpha()]
            
            # Take first 3 characters or pad with 'X' if insufficient
            name_prefix = ''.join(alphabetic_chars[:PREFIX_LENGTH])
            if len(name_prefix) < PREFIX_LENGTH:
                name_prefix = name_prefix.ljust(PREFIX_LENGTH, PADDING_CHAR)
            
            # Get count of existing organisations with similar pattern using safe parameterized query
            # Validate prefix is safe (only uppercase letters)
            if not name_prefix.isalpha() or not name_prefix.isupper():
                logger.warning("Invalid prefix '%s', using default", name_prefix)
                name_prefix = PADDING_CHAR * PREFIX_LENGTH
            
            pattern_base = f"{name_prefix}{current_year}"
            try:
                count_stmt = select(func.count()).select_from(Organisation).where(
                    Organisation.code.like(pattern_base + '%')
                )
                count_result = await self.db.execute(count_stmt)
                existing_count = count_result.scalar() or 0
            except SQLAlchemyError as db_error:
                logger.error("Database error counting existing organisation codes: %s", db_error)
                # Default to 0 to allow code generation to continue
                existing_count = 0
            
            # Ensure we don't exceed reasonable limits (999 organisations per year per prefix)
            if existing_count >= 999:
                logger.warning(f"High organisation count for prefix {name_prefix}{current_year}: {existing_count}")
            
            return f"{name_prefix}{current_year}{existing_count + 1:03d}"
            
        except HTTPException:
            raise
        except SQLAlchemyError as e:
            # Sanitize inputs to prevent code injection
            sanitized_name = str(name).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:100]
            sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
            logger.error(f"Database error generating organisation code for '{sanitized_name}': {sanitized_error}")
            raise HTTPException(
                status_code=500, 
                detail="Database error occurred while generating organisation code"
            )
        except ValueError as e:
            sanitized_name = str(name).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:100]
            sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
            logger.error(f"Value error generating organisation code for '{sanitized_name}': {sanitized_error}")
            raise HTTPException(
                status_code=400, 
                detail="Invalid organisation name provided"
            )
        except Exception as e:
            sanitized_name = str(name).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:100]
            sanitized_error = str(e).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')[:200]
            logger.error(f"Unexpected error generating organisation code for '{sanitized_name}': {sanitized_error}")
            raise HTTPException(
                status_code=500, 
                detail="An unexpected error occurred while generating organisation code"
            )
    
    # BULK OPERATIONS USING SQLALCHEMY ORM FOR SAFETY
    
    async def bulk_import_organisations(self, organisations_data: List[dict]) -> dict:
        """Bulk import organisations using SQLAlchemy for safety with optimized organisation code generation"""
        if not organisations_data:
            raise HTTPException(status_code=400, detail="No organisation data provided")
        
        try:
            # Process in batches to avoid memory issues
            batch_size = 100
            successful_imports = 0
            validation_errors = []
            now = datetime.now(timezone.utc)
            current_year = now.year
            
            # Cache for organisation code prefixes to avoid repeated DB queries
            prefix_counts = {}
            
            for batch_start in range(0, len(organisations_data), batch_size):
                batch = organisations_data[batch_start:batch_start + batch_size]
                batch_records = []
                
                # Pre-generate organisation codes for batch to optimize DB queries
                codes_needed = []
                for idx, organisation_data in enumerate(batch, start=batch_start):
                    if not organisation_data.get("code") and organisation_data.get("name"):
                        codes_needed.append((idx, organisation_data["name"]))
                
                # Batch generate organisation codes
                generated_codes = await self._batch_generate_codes(codes_needed, prefix_counts, current_year)
                
                for idx, organisation_data in enumerate(batch, start=batch_start):
                    organisation_result = self._validate_and_create_organisation(organisation_data, idx, generated_codes, now)
                    if organisation_result["error"]:
                        validation_errors.append(organisation_result["error"])
                    else:
                        batch_records.append(organisation_result["organisation"])
                
                # Bulk insert batch using PostgreSQL UPSERT
                if batch_records:
                    try:
                        self.db.add_all(batch_records)
                        await self.db.flush()
                        successful_imports += len(batch_records)
                    except IntegrityError as e:
                        await self.db.rollback()
                        logger.warning(f"Batch insert failed due to integrity error: {e}")
                        # Try individual inserts for this batch
                        for organisation in batch_records:
                            try:
                                self.db.add(organisation)
                                await self.db.flush()
                                successful_imports += 1
                            except IntegrityError:
                                await self.db.rollback()
                                validation_errors.append(f"Duplicate organisation: {organisation.email}")
            
            try:
                await self.db.commit()
            except SQLAlchemyError as e:
                await self.db.rollback()
                logger.error(f"Failed to commit bulk import changes: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to save organisation import changes"
                )
            
            return {
                "total_records_processed": len(organisations_data),
                "successful_imports": successful_imports,
                "failed_imports": len(validation_errors),
                "validation_errors": validation_errors[:10],  # Limit error list
                "status": "success"
            }
            
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Bulk import failed: {e}")
            raise HTTPException(status_code=500, detail=f"Bulk import failed: {str(e)}")
    
    async def _validate_batch_inputs(self, names: List[tuple], prefix_counts: dict, current_year: int) -> None:
        """Validate inputs for batch organisation code generation"""
        if not isinstance(names, list) or not isinstance(prefix_counts, dict):
            raise HTTPException(status_code=400, detail="Invalid input parameters for organisation code generation")
        
        if not isinstance(current_year, int) or current_year < 2000 or current_year > 2100:
            raise HTTPException(status_code=400, detail="Invalid year for organisation code generation")
        
        if not self.db:
            raise HTTPException(status_code=500, detail="Database connection not available")

    async def _get_prefix_counts(self, prefix_groups: dict, prefix_counts: dict, current_year: int) -> dict:
        """Get counts for all unique prefixes using optimized single query"""
        new_prefixes = [prefix for prefix in prefix_groups.keys() if prefix not in prefix_counts]
        if not new_prefixes:
            return prefix_counts
        
        try:
            # Validate database connection
            if not self.db:
                logger.error("Database connection not available for prefix counts")
                for prefix in new_prefixes:
                    prefix_counts[prefix] = 0
                return prefix_counts
            
            # Build single query with CASE statements for all prefixes
            case_statements = []
            for prefix in new_prefixes:
                pattern = f"{prefix}{current_year}%"
                case_statements.append(
                    func.sum(func.case((Organisation.code.like(pattern), 1), else_=0)).label(f"count_{prefix}")
                )
            
            count_stmt = select(*case_statements)
            count_result = await self.db.execute(count_stmt)
            counts = count_result.fetchone()
            
            # Update prefix_counts with results
            for prefix in new_prefixes:
                prefix_counts[prefix] = getattr(counts, f"count_{prefix}", 0) or 0
                
        except SQLAlchemyError as e:
            logger.error("Database error getting prefix counts: %s", e)
            # Fallback: set all new prefixes to 0
            for prefix in new_prefixes:
                prefix_counts[prefix] = 0
        except AttributeError as e:
            logger.error("Attribute error getting prefix counts: %s", e)
            # Fallback: set all new prefixes to 0
            for prefix in new_prefixes:
                prefix_counts[prefix] = 0
        except Exception as e:
            logger.error("Unexpected error getting prefix counts: %s", e)
            # Fallback: set all new prefixes to 0
            for prefix in new_prefixes:
                prefix_counts[prefix] = 0
        
        return prefix_counts

    async def _batch_generate_codes(self, names: List[tuple], prefix_counts: dict, current_year: int) -> dict:
        """Efficiently generate organisation codes in batch to minimize DB queries"""
        if not names:
            return {}
        
        try:
            await self._validate_batch_inputs(names, prefix_counts, current_year)
            
            PREFIX_LENGTH = 3
            PADDING_CHAR = 'X'
            
            # Group by prefix to minimize DB queries
            prefix_groups, failed_generations = self._group_by_prefix(
                names, PREFIX_LENGTH, PADDING_CHAR
            )
            
            # Update prefix counts
            prefix_counts = await self._get_prefix_counts(prefix_groups, prefix_counts, current_year)
            
            # Generate codes for each group
            generated_codes, additional_failures = self._generate_codes_for_groups(
                prefix_groups, prefix_counts, current_year
            )
            
            # Log failures if any
            if failed_generations or additional_failures:
                total_failures = len(failed_generations) + len(additional_failures)
                logger.warning(f"Organisation code generation completed with {len(generated_codes)} successes and {total_failures} failures")
            
            return generated_codes
            
        except HTTPException:
            raise
        except (SQLAlchemyError, ValueError, TypeError) as e:
            error_type = type(e).__name__
            logger.error(f"{error_type} in batch organisation code generation: {e}")
            raise HTTPException(
                status_code=500 if isinstance(e, SQLAlchemyError) else 400,
                detail=f"Error occurred while generating organisation codes: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Unexpected error in batch organisation code generation: {e}")
            raise HTTPException(
                status_code=500,
                detail="An unexpected error occurred while generating organisation codes"
            )
    
    def _generate_safe_prefix(self, name: str, prefix_length: int, padding_char: str) -> str:
        """Generate a safe prefix from organisation name with proper validation"""
        if not name or not isinstance(name, str):
            return padding_char * prefix_length
        
        # Extract only alphabetic characters and convert to uppercase
        alphabetic_chars = [c.upper() for c in name if c.isalpha()]
        
        # Take first N characters
        name_prefix = ''.join(alphabetic_chars[:prefix_length])
        
        # Pad with safe character if insufficient length
        if len(name_prefix) < prefix_length:
            name_prefix = name_prefix.ljust(prefix_length, padding_char)
        
        # Validate prefix contains only safe characters (A-Z, X)
        if not all(c.isalpha() and c.isupper() for c in name_prefix):
            logger.warning(f"Invalid characters in prefix '{name_prefix}', using default")
            return padding_char * prefix_length
        
        return name_prefix
    
    def _validate_and_create_organisation(self, organisation_data: dict, idx: int, generated_codes: dict, timestamp: datetime) -> dict:
        """Validate organisation data and create organisation object"""
        try:
            # Validate required fields
            missing_fields = [field for field in self.REQUIRED_ORGANISATION_FIELDS if not organisation_data.get(field)]
            if missing_fields:
                return {"error": f"Row {idx + 1}: Missing fields: {', '.join(missing_fields)}", "organisation": None}
            
            # Use pre-generated organisation code or existing one
            code = organisation_data.get("code") or generated_codes.get(idx)
            
            # Create organisation object
            organisation = self._create_organisation_from_data(organisation_data, code, timestamp)
            return {"error": None, "organisation": organisation}
            
        except Exception as e:
            return {"error": f"Row {idx + 1}: {str(e)}", "organisation": None}
    
    def _create_organisation_from_data(self, organisation_data: dict, code: str, timestamp: datetime) -> Organisation:
        """Create a Organisation object from validated data"""
        return Organisation(
            id=uuid.uuid4(),
            code=code,
            name=organisation_data["name"],
            address=organisation_data["address"],
            phone=organisation_data["phone"],
            email=organisation_data["email"],
            head_name=organisation_data["head_name"],
            is_active=organisation_data.get("is_active", True),
            annual_tuition=organisation_data["annual_tuition"],
            registration_fee=organisation_data["registration_fee"],
            charges_applied=organisation_data.get("charges_applied", False),
            charges_amount=organisation_data.get("charges_amount"),
            maximum_capacity=organisation_data["maximum_capacity"],
            org_type=organisation_data.get("org_type", "Organisation"),
            levels_offered=organisation_data.get("levels_offered"),
            established_year=organisation_data.get("established_year"),
            accreditation=organisation_data.get("accreditation"),
            language_of_instruction=organisation_data.get("language_of_instruction", "English"),
            created_at=timestamp,
            updated_at=timestamp,
            is_deleted=False
        )
    
    def _group_by_prefix(self, names: List[tuple], prefix_length: int, padding_char: str) -> tuple:
        """Group organisations by their generated prefix"""
        prefix_groups = {}
        failed_generations = []
        
        for idx, name in names:
            try:
                prefix = self._generate_safe_prefix(name, prefix_length, padding_char)
                if prefix not in prefix_groups:
                    prefix_groups[prefix] = []
                prefix_groups[prefix].append(idx)
            except Exception as e:
                logger.warning(f"Failed to generate prefix for organisation '{name}': {e}")
                failed_generations.append(f"Index {idx}: Invalid organisation name")
        
        return prefix_groups, failed_generations
    
    def _generate_codes_for_groups(self, prefix_groups: dict, prefix_counts: dict, current_year: int) -> tuple:
        """Generate organisation codes for grouped prefixes"""
        generated_codes = {}
        failed_generations = []
        
        for prefix, indices in prefix_groups.items():
            try:
                base_count = prefix_counts.get(prefix, 0)
                for i, idx in enumerate(indices):
                    try:
                        sequence_num = base_count + i + 1
                        if sequence_num > 999:
                            logger.warning(f"Sequence number {sequence_num} exceeds limit for prefix {prefix}")
                            sequence_num = 999
                        
                        generated_code = f"{prefix}{current_year}{sequence_num:03d}"
                        generated_codes[idx] = generated_code
                    # amazonq-ignore-next-line
                    except Exception as e:
                        logger.error(f"Error generating code for index {idx}: {e}")
                        failed_generations.append(f"Index {idx}: Code generation failed")
                
                prefix_counts[prefix] = base_count + len(indices)
            # amazonq-ignore-next-line
            except Exception as e:
                logger.error(f"Error processing prefix group '{prefix}': {e}")
                for idx in indices:
                    failed_generations.append(f"Index {idx}: Prefix processing failed")
        
        return generated_codes, failed_generations
    
    async def bulk_update_status(self, organisation_ids: List[UUID], is_active: bool) -> dict:
        """Bulk update organisation active status using SQLAlchemy"""
        if not organisation_ids:
            raise HTTPException(status_code=400, detail="No organisation IDs provided")
        
        try:
            # Use SQLAlchemy update with proper parameterization
            stmt = (
                update(Organisation)
                .where(
                    and_(
                        Organisation.id.in_(organisation_ids),
                        Organisation.is_deleted.is_(False)
                    )
                )
                .values(
                    is_active=is_active,
                    updated_at=datetime.now(timezone.utc)
                )
            )
            
            try:
                result = await self.db.execute(stmt)
            except SQLAlchemyError as e:
                logger.error(f"Failed to execute status update query: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Database error occurred during status update execution"
                )
            
            try:
                await self.db.commit()
                logger.info(f"Successfully updated {result.rowcount} organisations to {'active' if is_active else 'inactive'} status")
            except SQLAlchemyError as e:
                await self.db.rollback()
                logger.error(f"Failed to commit status update changes: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to save status update changes"
                )
            
            return {
                "updated_organisations": result.rowcount,
                "new_status": "active" if is_active else "inactive",
                "status": "success"
            }
            
        except SQLAlchemyError as e:
            await self.db.rollback()
            logger.error(f"Bulk status update failed: {e}")
            raise HTTPException(status_code=500, detail=f"Bulk status update failed: {str(e)}")
    
    async def bulk_update_capacity(self, capacity_updates: List[dict]) -> dict:
        """Bulk update organisation maximum capacity using SQLAlchemy with proper validation"""
        if not capacity_updates:
            raise HTTPException(status_code=400, detail="No capacity update data provided")
        
        try:
            updated_count = 0
            validation_errors = []
            
            # Process updates individually with proper validation
            for idx, capacity_update in enumerate(capacity_updates):
                try:
                    # Validate and sanitize organisation_id
                    organisation_id_raw = capacity_update.get("organisation_id")
                    if not organisation_id_raw:
                        validation_errors.append(f"Update {idx + 1}: Missing organisation_id")
                        continue
                    
                    # Ensure organisation_id is a valid UUID
                    try:
                        if isinstance(organisation_id_raw, str):
                            organisation_id = UUID(organisation_id_raw)
                        elif isinstance(organisation_id_raw, UUID):
                            organisation_id = organisation_id_raw
                        else:
                            validation_errors.append(f"Update {idx + 1}: Invalid organisation_id type")
                            continue
                    except (ValueError, TypeError) as e:
                        validation_errors.append(f"Update {idx + 1}: Invalid organisation_id format")
                        continue
                    
                    # Validate and sanitize new_capacity
                    new_capacity_raw = capacity_update.get("new_capacity")
                    if new_capacity_raw is None:
                        validation_errors.append(f"Update {idx + 1}: Missing new_capacity")
                        continue
                    
                    try:
                        new_capacity = int(new_capacity_raw)
                        if new_capacity <= 0 or new_capacity > 100000:  # Reasonable limits
                            validation_errors.append(f"Update {idx + 1}: Invalid capacity value (must be 1-100000)")
                            continue
                    except (ValueError, TypeError):
                        validation_errors.append(f"Update {idx + 1}: Invalid capacity format")
                        continue
                    
                    # Execute update with validated parameters
                    stmt = (
                        update(Organisation)
                        .where(
                            and_(
                                Organisation.id == organisation_id,
                                Organisation.is_deleted.is_(False)
                            )
                        )
                        .values(
                            maximum_capacity=new_capacity,
                            updated_at=datetime.now(timezone.utc)
                        )
                    )
                    
                    try:
                        result = await self.db.execute(stmt)
                        if result.rowcount > 0:
                            updated_count += 1
                        elif result.rowcount == 0:
                            validation_errors.append(f"Update {idx + 1}: Organisation not found or already deleted")
                    except SQLAlchemyError as db_error:
                        logger.error(f"Database execution error for capacity update {idx + 1}: {db_error}")
                        validation_errors.append(f"Update {idx + 1}: Database execution failed")
                        continue
                        
                except SQLAlchemyError as e:
                    logger.error(f"Database error processing capacity update {idx + 1}: {e}")
                    validation_errors.append(f"Update {idx + 1}: Database error occurred")
                    # Continue processing other updates
                except ValueError as e:
                    logger.error(f"Value error processing capacity update {idx + 1}: {e}")
                    validation_errors.append(f"Update {idx + 1}: Invalid data value")
                except TypeError as e:
                    logger.error(f"Type error processing capacity update {idx + 1}: {e}")
                    validation_errors.append(f"Update {idx + 1}: Invalid data type")
                except Exception as e:
                    logger.error(f"Unexpected error processing capacity update {idx + 1}: {e}")
                    validation_errors.append(f"Update {idx + 1}: Unexpected error occurred")
            
            await self.db.commit()
            
            return {
                "updated_organisations": updated_count,
                "total_requests": len(capacity_updates),
                "validation_errors": validation_errors[:10] if validation_errors else [],
                "status": "success" if not validation_errors else "partial_success"
            }
            
        except SQLAlchemyError as e:
            await self.db.rollback()
            logger.error(f"Critical database error in bulk capacity update: {e}")
            raise HTTPException(
                status_code=500, 
                detail="Database error occurred during bulk capacity update"
            )
        except ValueError as e:
            await self.db.rollback()
            logger.error(f"Value error in bulk capacity update: {e}")
            raise HTTPException(
                status_code=400, 
                detail="Invalid data provided for capacity update"
            )
        except TypeError as e:
            await self.db.rollback()
            logger.error(f"Type error in bulk capacity update: {e}")
            raise HTTPException(
                status_code=400, 
                detail="Invalid data types provided for capacity update"
            )
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Unexpected error in bulk capacity update: {e}")
            raise HTTPException(
                status_code=500, 
                detail="An unexpected error occurred during bulk capacity update"
            )
    
    async def bulk_update_financial_info(self, financial_updates: List[dict]) -> dict:
        """Bulk update organisation financial information using SQLAlchemy with proper validation"""
        if not financial_updates:
            raise HTTPException(status_code=400, detail="No financial update data provided")
        
        try:
            updated_count = 0
            validation_errors = []
            
            for idx, financial_update in enumerate(financial_updates):
                try:
                    # Validate organisation_id
                    organisation_id_raw = financial_update.get("organisation_id")
                    if not organisation_id_raw:
                        validation_errors.append(f"Update {idx + 1}: Missing organisation_id")
                        continue
                    
                    try:
                        organisation_id = UUID(organisation_id_raw) if isinstance(organisation_id_raw, str) else organisation_id_raw
                    except (ValueError, TypeError):
                        validation_errors.append(f"Update {idx + 1}: Invalid organisation_id format")
                        continue
                    
                    # Build update values with validation
                    update_values = {"updated_at": datetime.now(timezone.utc)}
                    
                    if "annual_tuition" in financial_update:
                        try:
                            tuition = float(financial_update["annual_tuition"])
                            if 0 <= tuition <= 1000000:
                                update_values["annual_tuition"] = tuition
                            else:
                                validation_errors.append(f"Update {idx + 1}: Invalid tuition value")
                        except (ValueError, TypeError):
                            validation_errors.append(f"Update {idx + 1}: Invalid tuition format")
                    
                    if "registration_fee" in financial_update:
                        try:
                            fee = float(financial_update["registration_fee"])
                            if 0 <= fee <= 100000:
                                update_values["registration_fee"] = fee
                            else:
                                validation_errors.append(f"Update {idx + 1}: Invalid fee value")
                        except (ValueError, TypeError):
                            validation_errors.append(f"Update {idx + 1}: Invalid fee format")
                    
                    if len(update_values) == 1:
                        validation_errors.append(f"Update {idx + 1}: No valid financial data")
                        continue
                    
                    stmt = (
                        update(Organisation)
                        .where(
                            and_(
                                Organisation.id == organisation_id,
                                Organisation.is_deleted.is_(False)
                            )
                        )
                        .values(**update_values)
                    )
                    
                    result = await self.db.execute(stmt)
                    if result.rowcount > 0:
                        updated_count += 1
                    elif result.rowcount == 0:
                        validation_errors.append(f"Update {idx + 1}: Organisation not found")
                        
                except SQLAlchemyError as e:
                    logger.error(f"Database error processing financial update {idx + 1}: {e}")
                    validation_errors.append(f"Update {idx + 1}: Database error occurred")
                except Exception as e:
                    logger.error(f"Error processing financial update {idx + 1}: {e}")
                    validation_errors.append(f"Update {idx + 1}: Processing failed")
            
            await self.db.commit()
            
            return {
                "updated_organisations": updated_count,
                "total_requests": len(financial_updates),
                "validation_errors": validation_errors[:10] if validation_errors else [],
                "status": "success" if not validation_errors else "partial_success"
            }
            
        except SQLAlchemyError as e:
            await self.db.rollback()
            logger.error(f"Critical database error in bulk financial update: {e}")
            raise HTTPException(
                status_code=500, 
                detail="Database error occurred during bulk financial update"
            )
        # amazonq-ignore-next-line
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Unexpected error in bulk financial update: {e}")
            raise HTTPException(
                status_code=500, 
                detail="An unexpected error occurred during bulk financial update"
            )
    
    async def bulk_update_charges(self, charges_updates: List[dict]) -> dict:
        """Bulk update organisation charges information"""
        if not charges_updates:
            raise HTTPException(status_code=400, detail="No charges update data provided")
        
        try:
            updated_count = 0
            validation_errors = []
            
            for idx, charges_update in enumerate(charges_updates):
                try:
                    organisation_id_raw = charges_update.get("organisation_id")
                    if not organisation_id_raw:
                        validation_errors.append(f"Update {idx + 1}: Missing organisation_id")
                        continue
                    
                    try:
                        organisation_id = UUID(organisation_id_raw) if isinstance(organisation_id_raw, str) else organisation_id_raw
                    except (ValueError, TypeError):
                        validation_errors.append(f"Update {idx + 1}: Invalid organisation_id format")
                        continue
                    
                    update_values = {"updated_at": datetime.now(timezone.utc)}
                    
                    if "charges_applied" in charges_update:
                        charges_applied = charges_update["charges_applied"]
                        if isinstance(charges_applied, bool):
                            update_values["charges_applied"] = charges_applied
                        else:
                            validation_errors.append(f"Update {idx + 1}: Invalid charges_applied value")
                            continue
                    
                    if "charges_amount" in charges_update:
                        try:
                            charges_amount = charges_update["charges_amount"]
                            if charges_amount is not None:
                                charges_amount = float(charges_amount)
                                if charges_amount < 0:
                                    validation_errors.append(f"Update {idx + 1}: Charges amount must be non-negative")
                                    continue
                            update_values["charges_amount"] = charges_amount
                        except (ValueError, TypeError):
                            validation_errors.append(f"Update {idx + 1}: Invalid charges_amount format")
                            continue
                    
                    if len(update_values) == 1:
                        validation_errors.append(f"Update {idx + 1}: No valid charges data")
                        continue
                    
                    stmt = (
                        update(Organisation)
                        .where(
                            and_(
                                Organisation.id == organisation_id,
                                Organisation.is_deleted.is_(False)
                            )
                        )
                        .values(**update_values)
                    )
                    
                    result = await self.db.execute(stmt)
                    if result.rowcount > 0:
                        updated_count += 1
                    elif result.rowcount == 0:
                        validation_errors.append(f"Update {idx + 1}: Organisation not found")
                        
                except SQLAlchemyError as e:
                    logger.error(f"Database error processing charges update {idx + 1}: {e}")
                    validation_errors.append(f"Update {idx + 1}: Database error occurred")
                except Exception as e:
                    logger.error(f"Error processing charges update {idx + 1}: {e}")
                    validation_errors.append(f"Update {idx + 1}: Processing failed")
            
            await self.db.commit()
            
            return {
                "updated_organisations": updated_count,
                "total_requests": len(charges_updates),
                "validation_errors": validation_errors[:10] if validation_errors else [],
                "status": "success" if not validation_errors else "partial_success"
            }
            
        except SQLAlchemyError as e:
            await self.db.rollback()
            logger.error(f"Critical database error in bulk charges update: {e}")
            raise HTTPException(
                status_code=500, 
                detail="Database error occurred during bulk charges update"
            )
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Unexpected error in bulk charges update: {e}")
            raise HTTPException(
                status_code=500, 
                detail="An unexpected error occurred during bulk charges update"
            )
    

    
    async def bulk_soft_delete(self, organisation_ids: List[UUID]) -> dict:
        """Bulk soft delete organisations using SQLAlchemy"""
        if not organisation_ids:
            raise HTTPException(status_code=400, detail="No organisation IDs provided")
        
        try:
            stmt = (
                update(Organisation)
                .where(
                    and_(
                        Organisation.id.in_(organisation_ids),
                        Organisation.is_deleted.is_(False)
                    )
                )
                .values(
                    is_deleted=True,
                    is_active=False,
                    updated_at=datetime.now(timezone.utc)
                )
            )
            
            result = await self.db.execute(stmt)
            # amazonq-ignore-next-line
            await self.db.commit()
            
            return {
                "deleted_organisations": result.rowcount,
                "status": "success"
            }
            
        except SQLAlchemyError as e:
            await self.db.rollback()
            logger.error(f"Bulk delete failed: {e}")
            raise HTTPException(status_code=500, detail=f"Bulk delete failed: {str(e)}")
    
    def _initialize_statistics_result(self) -> dict:
        """Initialize default statistics result structure"""
        return {
            "total_organisations": 0,
            "active_organisations": 0,
            "inactive_organisations": 0,
            "activation_rate": 0.0,
            "total_capacity": 0,
            "average_tuition": 0.0,
            "total_registration_fees": 0.0,
            "oldest_org_year": None,
            "newest_org_year": None,
            "org_type_distribution": {},
            "language_distribution": {},
            "accreditation_distribution": {},
            "financial_summary": {
                "total_annual_revenue": 0.0,
                "average_tuition": 0.0,
                "average_registration_fee": 0.0,
                "tuition_range": {"min": 0.0, "max": 0.0}
            },
            "errors": []
        }
    
    async def _get_basic_counts(self, result: dict) -> None:
        """Get basic organisation counts and update result"""
        try:
            counts_query = select(
                func.count().label('total'),
                func.sum(func.case((Organisation.is_active.is_(True), 1), else_=0)).label('active')
            ).where(Organisation.is_deleted.is_(False))
            
            counts_result = await self.db.execute(counts_query)
            counts = counts_result.fetchone()
            
            total_count = counts.total or 0
            active_count = counts.active or 0
            
            result.update({
                "total_organisations": total_count,
                "active_organisations": active_count,
                "inactive_organisations": total_count - active_count,
                "activation_rate": round((active_count / total_count * 100), 2) if total_count > 0 else 0.0
            })
        except SQLAlchemyError as e:
            logger.error(f"Error getting basic organisation counts: {e}")
            result["errors"].append("Basic counts unavailable")
    
    async def _get_aggregated_stats(self, result: dict) -> None:
        """Get aggregated statistics and update result"""
        try:
            stats_query = select(
                func.sum(Organisation.maximum_capacity).label('total_capacity'),
                func.avg(Organisation.annual_tuition).label('average_tuition'),
                func.sum(Organisation.registration_fee).label('total_reg_fees'),
                func.avg(Organisation.registration_fee).label('avg_reg_fee'),
                func.min(Organisation.annual_tuition).label('min_tuition'),
                func.max(Organisation.annual_tuition).label('max_tuition'),
                func.min(Organisation.established_year).label('oldest_year'),
                func.max(Organisation.established_year).label('newest_year')
            ).where(Organisation.is_deleted.is_(False))
            
            stats_result = await self.db.execute(stats_query)
            stats = stats_result.fetchone()
            
            if stats:
                try:
                    avg_tuition = float(stats.average_tuition) if stats.average_tuition else 0.0
                except (ValueError, TypeError):
                    avg_tuition = 0.0
                
                result.update({
                    "total_capacity": stats.total_capacity or 0,
                    "average_tuition": avg_tuition,
                    "total_registration_fees": float(stats.total_reg_fees) if stats.total_reg_fees else 0.0,
                    "oldest_org_year": stats.oldest_year,
                    "newest_org_year": stats.newest_year
                })
                
                result["financial_summary"] = {
                    "total_annual_revenue": 0.0,
                    "average_tuition": float(stats.average_tuition) if stats.average_tuition else 0.0,
                    "average_registration_fee": float(stats.avg_reg_fee) if stats.avg_reg_fee else 0.0,
                    "tuition_range": {
                        "min": float(stats.min_tuition) if stats.min_tuition else 0.0,
                        "max": float(stats.max_tuition) if stats.max_tuition else 0.0
                    }
                }
        except SQLAlchemyError as e:
            logger.error(f"Error getting aggregated statistics: {e}")
            result["errors"].append("Aggregated statistics unavailable")
        except (ValueError, TypeError, ZeroDivisionError) as e:
            logger.error(f"Error calculating statistics: {e}")
            result["errors"].append("Statistics calculation error")
    
    async def _get_distributions(self, result: dict) -> None:
        """Get various distribution statistics"""
        distributions = [
            ("org_type", Organisation.org_type, "org_type_distribution"),
            ("language_of_instruction", Organisation.language_of_instruction, "language_distribution")
        ]
        
        for name, field, key in distributions:
            try:
                query = select(field, func.count().label('count')).where(
                    and_(Organisation.is_deleted.is_(False), Organisation.is_active.is_(True))
                ).group_by(field).order_by(func.count().desc())
                
                query_result = await self.db.execute(query)
                result[key] = {getattr(row, field.name): row.count for row in query_result.fetchall()}
            except SQLAlchemyError as e:
                logger.error(f"Error getting {name} distribution: {e}")
                result["errors"].append(f"{name.title()} distribution unavailable")
        
        # Accreditation distribution (with null check)
        try:
            accred_query = select(Organisation.accreditation, func.count().label('count')).where(
                and_(Organisation.is_deleted.is_(False), Organisation.is_active.is_(True), Organisation.accreditation.isnot(None))
            ).group_by(Organisation.accreditation).order_by(func.count().desc())
            
            accred_result = await self.db.execute(accred_query)
            result["accreditation_distribution"] = {row.accreditation: row.count for row in accred_result.fetchall()}
        except SQLAlchemyError as e:
            logger.error(f"Error getting accreditation distribution: {e}")
            result["errors"].append("Accreditation distribution unavailable")
    
    async def get_comprehensive_statistics(self) -> dict:
        """Get comprehensive organisation statistics using SQLAlchemy with graceful error handling"""
        try:
            if not self.db:
                raise HTTPException(status_code=500, detail="Database connection not available")
            
            result = self._initialize_statistics_result()
            
            await self._get_basic_counts(result)
            await self._get_aggregated_stats(result)
            await self._get_distributions(result)
            
            if not result["errors"]:
                del result["errors"]
            
            return result
            
        except HTTPException:
            raise
        except SQLAlchemyError as e:
            logger.error(f"Critical database error getting comprehensive statistics: {e}")
            raise HTTPException(status_code=500, detail="Database error occurred while fetching comprehensive statistics")
        except ValueError as e:
            logger.error(f"Value error getting comprehensive statistics: {e}")
            raise HTTPException(status_code=400, detail="Invalid data encountered while calculating statistics")
        except Exception as e:
            logger.error(f"Unexpected error getting comprehensive statistics: {e}")
            raise HTTPException(status_code=500, detail="An unexpected error occurred while fetching comprehensive statistics")
