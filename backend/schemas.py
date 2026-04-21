from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    id: int
    api_key: Optional[str] = None
    storage_quota_gb: float
    used_storage_gb: float
    stripe_customer_id: Optional[str] = None

    class Config:
        from_attributes = True

class JobBase(BaseModel):
    video_name: str

class JobCreate(JobBase):
    user_id: int

class JobResponse(JobBase):
    id: int
    user_id: int
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    result_url: Optional[str] = None

    class Config:
        from_attributes = True

class StorageUsage(BaseModel):
    used_storage_gb: float
    storage_quota_gb: float
