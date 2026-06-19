import hashlib
import ipaddress
from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.auth import User, Session as UserSession
from app.models.profile import CandidateProfile, Preferences
from app.utils.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token

def hash_token(token: str) -> str:
    """Helper to return sha256 hash of a token string."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sanitize_ip(raw: Optional[str]) -> Optional[str]:
    """Return a validated IPv4/IPv6 string, or None if not a valid IP.

    PostgreSQL's INET column rejects non-IP strings such as 'testclient'
    (the fake host that Starlette's TestClient sends).  Rather than letting
    the INSERT fail with a DBAPIError we simply store NULL for unknown hosts.
    """
    if not raw:
        return None
    try:
        ipaddress.ip_address(raw)
        return raw
    except ValueError:
        return None

class AuthService:
    @staticmethod
    async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
        stmt = select(User).where(User.email == email)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id) -> Optional[User]:
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def register_user(db: AsyncSession, email: str, password_plain: str, full_name: str, phone: Optional[str] = None) -> User:
        # 1. Create User
        hashed = hash_password(password_plain)
        new_user = User(
            email=email,
            hashed_password=hashed,
            full_name=full_name,
            phone=phone
        )
        db.add(new_user)
        await db.flush() # populated the user ID

        # 2. Create Candidate Profile
        profile = CandidateProfile(user_id=new_user.id)
        db.add(profile)

        # 3. Create Preferences Default values
        prefs = Preferences(user_id=new_user.id)
        db.add(prefs)

        await db.commit()
        await db.refresh(new_user)
        return new_user

    @staticmethod
    async def login_user(db: AsyncSession, email: str, password_plain: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> Optional[Tuple[User, str, str]]:
        user = await AuthService.get_user_by_email(db, email)
        if not user or not verify_password(password_plain, user.hashed_password):
            return None

        # Update last login time
        user.last_login_at = datetime.now(timezone.utc)
        db.add(user)

        # Generate tokens
        access_token = create_access_token(user.id)
        refresh_token = create_refresh_token(user.id)

        # Decode refresh token to get expiry
        decoded_refresh = decode_token(refresh_token)
        expires_at = datetime.fromtimestamp(decoded_refresh["exp"], timezone.utc)

        # Store session token hashes in auth.sessions
        access_hash = hash_token(access_token)
        refresh_hash = hash_token(refresh_token)

        new_session = UserSession(
            user_id=user.id,
            access_token_hash=access_hash,
            refresh_token_hash=refresh_hash,
            expires_at=expires_at,
            ip_address=_sanitize_ip(ip_address),
            user_agent=user_agent
        )
        db.add(new_session)
        await db.commit()
        
        return user, access_token, refresh_token

    @staticmethod
    async def refresh_tokens(db: AsyncSession, refresh_token: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> Optional[Tuple[str, str]]:
        # Decode and verify refresh token payload
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            return None

        user_id = payload.get("sub")
        if not user_id:
            return None

        # Verify refresh token hash in DB
        refresh_hash = hash_token(refresh_token)
        stmt = select(UserSession).where(UserSession.refresh_token_hash == refresh_hash)
        result = await db.execute(stmt)
        session = result.scalars().first()

        if not session or session.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            if session:
                await db.delete(session)
                await db.commit()
            return None

        # Revoke old session
        await db.delete(session)

        # Generate new tokens
        access_token = create_access_token(user_id)
        new_refresh_token = create_refresh_token(user_id)
        
        # Save new session
        decoded_refresh = decode_token(new_refresh_token)
        expires_at = datetime.fromtimestamp(decoded_refresh["exp"], timezone.utc)
        
        new_session = UserSession(
            user_id=session.user_id,
            access_token_hash=hash_token(access_token),
            refresh_token_hash=hash_token(new_refresh_token),
            expires_at=expires_at,
            ip_address=_sanitize_ip(ip_address),
            user_agent=user_agent
        )
        db.add(new_session)
        await db.commit()

        return access_token, new_refresh_token

    @staticmethod
    async def logout_user(db: AsyncSession, access_token: str) -> bool:
        access_hash = hash_token(access_token)
        stmt = select(UserSession).where(UserSession.access_token_hash == access_hash)
        result = await db.execute(stmt)
        session = result.scalars().first()

        if session:
            await db.delete(session)
            await db.commit()
            return True
        return False
