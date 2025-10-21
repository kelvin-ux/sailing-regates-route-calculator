import math
import time
from contextvars import ContextVar
from typing import Any
from typing import Dict
from typing import Generic
from typing import List
from typing import Type
from typing import TypeVar

from fastapi import HTTPException
from fastapi import Request
from pydantic import BaseModel
from pydantic import UUID4
from sqlalchemy import and_
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import Base

T = TypeVar("T", bound=BaseModel)  # Response or request model
C = TypeVar("C", bound=Base)  # Base ORM model

request_context: ContextVar[Request] = ContextVar("request_context")


class BaseService(Generic[C]):
    def __init__(self, session: AsyncSession, model: Type[C]):
        self.session = session
        self.model = model
        self.name = self.__class__.__name__

    def __repr__(self):
        return f"{self.__class__.__name__} ({self.session}, {self.model})"

    def __str__(self):
        return f"{self.__class__.__name__}"

    @staticmethod
    def build_paginated_response(page: int, limit: int, total_count: int, items: List[C], filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a paginated response with links to the first, last, next, and previous pages."""
        request: Request = request_context.get()

        total_pages = (total_count + limit - 1)
        last_page = math.ceil(total_count / limit)
        has_next = page < total_pages
        has_previous = 1 < page <= total_pages + 1

        def _(page_number: int) -> str:
            link = request.url.query.replace(f'page={page}&size={limit}', f'page={page_number}&size={limit}')
            link = f"{request.url.path}?{link}"
            return link

        links = {
            "first": _(1) if total_pages > 0 else None,
            "last": _(last_page) if last_page > 0 else None,
            "next": _(page + 1) if has_next else None,
            "previous": _(page - 1) if has_previous else None,
        }

        response: dict[str, Any] = {
            "timestamp": int(time.time()),
            "filters": {key: value for key, value in filters.items() if value is not None} if filters else {},
            "data": {
                "total": total_count,
                "page": page,
                "size": limit,
                "items": items
            },
            "links": links,
        }

        return response

    def apply_selectinload_relations(self, query, relations: list[str]):
        """Add selectinload options to query."""
        options = []
        for relation in relations:
            if hasattr(self.model, relation):
                options.append(selectinload(getattr(self.model, relation)))
            else:
                raise AttributeError(f"Model {self.model.__name__} has no attribute '{relation}'")
        return query.options(*options)

    async def safe_commit(self):
        """Safe commit."""
        try:
            await self.session.commit()
        except SQLAlchemyError as e:
            await self.session.rollback()
            raise HTTPException(status_code=500, detail=f"Database error: {e}")

    async def get_or_create(self, model_data: T, load_relations: list[str] = None, **kwargs) -> C:
        """Get or create entity. Treat this as experimental."""
        entity = await self.get_entity_by_field(load_relations=load_relations, **kwargs)
        if entity:
            return entity
        else:
            new_entity = await self.create_entity(model_data=model_data, load_relations=load_relations, **kwargs)
            return new_entity

    async def get_entity_by_field(self, load_relations: list[str] = None, **kwargs) -> C:
        """Get entity by fields names and values."""
        if not kwargs:
            raise ValueError("No query fields provided.")
        filters = [getattr(self.model, field) == value for field, value in kwargs.items()]
        query = select(self.model).where(*filters)
        if load_relations:
            query = self.apply_selectinload_relations(query, load_relations)
        result = await self.session.execute(query)
        entity = result.scalar_one_or_none()
        return entity

    async def create_entity(self, model_data: T, load_relations: list[str] = None, **kwargs) -> C:
        """Create entity if it does not exist."""
        if kwargs:
            existing = await self.get_entity_by_field(load_relations=load_relations, **kwargs)
            if existing:
                raise HTTPException(status_code=409, detail=f"{self.model.__name__} already exists")

        new_entity = self.model(**model_data.model_dump())
        self.session.add(new_entity)
        await self.safe_commit()

        if load_relations:
            query = select(self.model)
            query = self.apply_selectinload_relations(query, load_relations)
            result = await self.session.execute(query.filter_by(id=new_entity.id))
            new_entity = result.scalar_one_or_none()

        return new_entity

    async def get_entity_by_id(self, entity_id: int | UUID4, allow_none: bool = True, load_relations: list[str] = None) -> C:
        """Get entity by id."""
        query = select(self.model)
        if load_relations:
            query = self.apply_selectinload_relations(query, load_relations)

        result = await self.session.execute(query.filter_by(id=entity_id))
        entity = result.scalar_one_or_none()
        if not allow_none and entity is None:
            raise HTTPException(status_code=404, detail=f"{self.model.__name__} not found")
        return entity

    async def get_all_entities(self, filters: Dict[str, Any] = None, page: int = 1, limit: int = 10) -> list[C]:
        """"Get all entities paginated."""
        if not filters:
            query = select(self.model)
        else:
            conditions = [getattr(self.model, field) == value for field, value in filters.items() if value]
            query = select(self.model).where(and_(*conditions))

        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)
        result = await self.session.execute(query)
        entities = [row for row in result.scalars()]

        return entities

    async def count_entities(self, filters: Dict[str, Any] = None):
        if not filters:
            count_query = select(func.count()).select_from(self.model)
        else:
            conditions = [getattr(self.model, field) == value for field, value in filters.items() if value]
            count_query = select(func.count()).select_from(self.model).where(and_(*conditions))
        total_result = await self.session.execute(count_query)
        total_count = total_result.scalar()
        return total_count

    async def remove_entity(self, model_data: T) -> C:
        """Remove entity."""
        item = await self.get_entity_by_id(model_data.id)
        if not item:
            raise HTTPException(status_code=404, detail=f"{self.model.__name__} not found.")
        await self.session.delete(item)
        await self.safe_commit()
        return item

    async def soft_remove_entity(self, model_data: T) -> C:
        """Soft remove entity."""
        entity = await self.get_entity_by_id(model_data.id, allow_none=False)
        if hasattr(entity, 'removed'):
            entity.removed = True
        else:
            raise AttributeError(f"{self.model.__name__} does not have a 'removed' field")

        await self.safe_commit()
        await self.session.refresh(entity)

        return entity

    async def update_entity(self, model_data: T) -> C:
        """Update entity."""
        entity = await self.get_entity_by_id(model_data.id, allow_none=False)
        data = model_data.model_dump(exclude_unset=True)
        for field, value in data.items():
            setattr(entity, field, value)
        await self.safe_commit()
        await self.session.refresh(entity)
        return entity
