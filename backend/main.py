from fastapi import FastAPI, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import List
import secrets

from .database import engine, get_db, Base
from . import models, schemas, r2_utils

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Remanence.io Backend")

def get_current_user(x_api_key: str = Header(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.api_key == x_api_key).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key"
        )
    return user

@app.post("/auth/register", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    new_user = models.User(email=user.email, api_key=secrets.token_urlsafe(32))
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.get("/user/storage", response_model=schemas.StorageUsage)
def get_storage(current_user: models.User = Depends(get_current_user)):
    return {
        "used_storage_gb": current_user.used_storage_gb,
        "storage_quota_gb": current_user.storage_quota_gb
    }

@app.post("/video/upload")
def upload_video(video_name: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    # In a real app, we'd check quota here
    
    presigned_url = r2_utils.generate_presigned_url(video_name)
    
    # Create a pending job
    job = models.Job(user_id=current_user.id, video_name=video_name, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    
    return {
        "upload_url": presigned_url,
        "job_id": job.id
    }

@app.get("/jobs", response_model=List[schemas.JobResponse])
def list_jobs(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(models.Job).filter(models.Job.user_id == current_user.id).all()

@app.get("/jobs/{job_id}", response_model=schemas.JobResponse)
def get_job(job_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.query(models.Job).filter(models.Job.id == job_id, models.Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
