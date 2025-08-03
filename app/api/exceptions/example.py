from fastapi import APIRouter
# from fastapi import Depends
# from pydantic import UUID4

# from app.services.example import get_something_service
# from app.services.example import SomethingService
#
router = APIRouter()
#
#
# @router.get("/{something_id}",
#             description="This endpoint returns a Something .",
#             status_code=200)
# async def get_something(something_id: UUID4, service: SomethingService = Depends(get_something_service)):
#     return await service.create_something(something_id)
