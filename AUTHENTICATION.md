# 3D REEL STUDIO — USER AUTHENTICATION & MULTI-USER ISOLATION (PHASE 16)

## 1. Overview & Architecture

Phase 16 introduces enterprise-grade user authentication and multi-tenant project isolation into **3D REEL STUDIO**. The security architecture guarantees that every user's creative assets—including video sources, audio extracts, whisper transcripts, scene keyframes, face/pose vectors, comic frames, character consistency profiles, SAM segmentation masks, kinetic lyric configs, and final 1080×1920 MP4 renders—are completely isolated.

```
                    ┌─────────────────────────┐
                    │     User / Client       │
                    └────────────┬────────────┘
                                 │
                     POST /api/v1/auth/login
                     POST /api/v1/auth/register
                                 ▼
                    ┌─────────────────────────┐
                    │   Signed JWT Token      │
                    │   (HMAC-SHA256 Sig)     │
                    └────────────┬────────────┘
                                 │
                 Authorization: Bearer <token>
                                 ▼
                    ┌─────────────────────────┐
                    │  FastAPI Security Layer │
                    │    get_current_user()   │
                    └────────────┬────────────┘
                                 │ Authenticated User ID
                                 ▼
                    ┌─────────────────────────┐
                    │   Project Ownership     │
                    │  project.user_id == uid │
                    └────────────┬────────────┘
                                 │
           ┌─────────────────────┼─────────────────────┐
           ▼                     ▼                     ▼
    ┌─────────────┐       ┌─────────────┐       ┌─────────────┐
    │ Media Files │       │ AI Pipeline │       │ Render Jobs │
    │   (Owned)   │       │  Artifacts  │       │  (1080x1920)│
    └─────────────┘       └─────────────┘       └─────────────┘
```

---

## 2. Authentication Flow & Endpoints

### 2.1 User Registration
- **Endpoint**: `POST /api/v1/auth/register`
- **Rate Limit**: 10 requests / minute per client IP
- **Request Body**:
  ```json
  {
    "email": "creator@example.com",
    "password": "SecurePassword123!"
  }
  ```
- **Validation Rules**:
  - `email`: Valid RFC email format, normalized to lowercase, unique across database.
  - `password`: Minimum 8 characters, maximum 128 characters.
- **Response**: `201 Created`
  ```json
  {
    "success": true,
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 86400,
    "user": {
      "id": "USR-8F4C2A10B389",
      "email": "creator@example.com",
      "is_active": true,
      "created_at": "2026-10-04T16:30:00Z"
    }
  }
  ```

### 2.2 User Login
- **Endpoint**: `POST /api/v1/auth/login`
- **Rate Limit**: 10 requests / minute per client IP
- **Request Body**:
  ```json
  {
    "email": "creator@example.com",
    "password": "SecurePassword123!"
  }
  ```
- **Response**: `200 OK` (returns fresh access token and user profile)
- **Error Response**: `401 Unauthorized` with generic message (`"Invalid email or password."`) preventing account enumeration.

### 2.3 Current User Profile
- **Endpoint**: `GET /api/v1/auth/me`
- **Headers**: `Authorization: Bearer <access_token>`
- **Response**: `200 OK`
  ```json
  {
    "success": true,
    "user": {
      "id": "USR-8F4C2A10B389",
      "email": "creator@example.com",
      "is_active": true,
      "created_at": "2026-10-04T16:30:00Z"
    }
  }
  ```

### 2.4 User Logout
- **Endpoint**: `POST /api/v1/auth/logout`
- **Headers**: `Authorization: Bearer <access_token>`
- **Response**: `200 OK`
  ```json
  {
    "success": true,
    "message": "Successfully logged out."
  }
  ```

---

## 3. Cryptographic Password Security

1. **Algorithm**: `PBKDF2-HMAC-SHA256`
2. **Iteration Count**: `600,000` (conforming to modern OWASP guidelines)
3. **Salt**: Cryptographically secure 16-byte random salt generated per user via `os.urandom(16)`.
4. **Storage Format**: `pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`
5. **Constant-Time Verification**: Verification utilizes `hmac.compare_digest` to prevent side-channel timing attacks.
6. **Zero Password Leakage**: Plaintext passwords and password hashes are never logged, serialized in API responses, or exposed to frontend bundles.

---

## 4. Token & Session Architecture

- **Token Format**: Standard JSON Web Token (JWT) with compact URL-safe Base64 serialization (`header.payload.signature`).
- **Signature Algorithm**: HMAC-SHA256 (`HS256`) signed with `AUTH_SECRET`.
- **Payload Claims**:
  - `sub`: User ID (`USR-...`)
  - `email`: Normalized user email
  - `iat`: Timestamp of issuance
  - `exp`: Expiration timestamp (default: 24 hours / 1440 minutes)
  - `jti`: Unique random token nonce
  - `iss`: `"3D REEL STUDIO"`
- **Validation**: Strict verification of signature integrity, timestamp expiration, and user account status (`is_active == True`).

---

## 5. Strict Project Ownership & ID Enumeration Defense

### 5.1 Project Creation & Listing
- Every project record in SQLite stores `user_id` referencing `users.id`.
- During `POST /api/v1/projects`, the backend unconditionally assigns `project.user_id = current_user.id`. The frontend cannot spoof ownership.
- `GET /api/v1/projects` filters projects strictly by `WHERE user_id = :current_user_id`.

### 5.2 Nested Resource Access Control
- All 25 async project API endpoints enforce project ownership via `get_owned_project(project_id, current_user, db)`.
- If an unauthenticated user or an attacker requests a project ID owned by another user:
  - **Returned Status**: `404 Not Found`
  - **Error Code**: `NOT_FOUND`
  - **Defense Rational**: Prevents attackers from discerning whether another user's project or media ID exists in the database (ID Enumeration Defense).

### 5.3 Isolation Matrix

| Operation | User A → User A Asset | User B → User B Asset | User A → User B Asset | User B → User A Asset |
| :--- | :---: | :---: | :---: | :---: |
| **Get Project Detail** | ✅ 200 OK | ✅ 200 OK | 🚫 404 Not Found | 🚫 404 Not Found |
| **Update Project** | ✅ 200 OK | ✅ 200 OK | 🚫 404 Not Found | 🚫 404 Not Found |
| **Upload Media** | ✅ 201 Created | ✅ 201 Created | 🚫 404 Not Found | 🚫 404 Not Found |
| **Download Media / File** | ✅ 200 OK | ✅ 200 OK | 🚫 404 Not Found | 🚫 404 Not Found |
| **Audio Extraction** | ✅ 200 OK | ✅ 200 OK | 🚫 404 Not Found | 🚫 404 Not Found |
| **Transcription** | ✅ 200 OK | ✅ 200 OK | 🚫 404 Not Found | 🚫 404 Not Found |
| **Scene & Vision Analysis** | ✅ 200 OK | ✅ 200 OK | 🚫 404 Not Found | 🚫 404 Not Found |
| **Comic Generation** | ✅ 200 OK | ✅ 200 OK | 🚫 404 Not Found | 🚫 404 Not Found |
| **Character Consistency** | ✅ 200 OK | ✅ 200 OK | 🚫 404 Not Found | 🚫 404 Not Found |
| **SAM Segmentation** | ✅ 200 OK | ✅ 200 OK | 🚫 404 Not Found | 🚫 404 Not Found |
| **Kinetic Lyrics Config** | ✅ 200 OK | ✅ 200 OK | 🚫 404 Not Found | 🚫 404 Not Found |
| **Render Reel Execution** | ✅ 200/202 | ✅ 200/202 | 🚫 404 Not Found | 🚫 404 Not Found |

---

## 6. Database Migration

Migration `003_user_auth_and_project_ownership` in `backend/app/db/migrations.py` applies the following changes:
1. Creates `users` table:
   - `id VARCHAR(36) PRIMARY KEY`
   - `email VARCHAR(255) UNIQUE NOT NULL`
   - `password_hash VARCHAR(255) NOT NULL`
   - `is_active BOOLEAN NOT NULL DEFAULT 1`
   - `created_at DATETIME NOT NULL`
   - `updated_at DATETIME NOT NULL`
   - `last_login_at DATETIME`
2. Creates default development user `USR-DEFAULT-DEV` (`dev@reelstudio.local`).
3. Adds `user_id VARCHAR(36) NOT NULL DEFAULT 'USR-DEFAULT-DEV'` to `projects` table with foreign key constraint and index on `user_id`.
4. Creates unique index `idx_users_email` on `users(email)` and `idx_projects_user_id` on `projects(user_id)`.

To run migrations manually:
```bash
python -c "from app.db.migrations import run_migrations; print(run_migrations())"
```

---

## 7. Environment Variables

Configure the following variables in `.env` (refer to `.env.example`):

```env
# Phase 16: Authentication & Security Configuration
AUTH_SECRET=reelstudio_dev_secret_key_change_in_production_2026!
AUTH_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
AUTH_RATE_LIMIT_PER_MINUTE=10
```

---

## 8. Frontend Integration

1. **Token Injection**: `apiRequest()` in `js/api.js` automatically includes `Authorization: Bearer <token>` for all API calls.
2. **Session Persistence**: Stores tokens and user state in `localStorage` (`reelstudio_access_token`).
3. **Auth Modal**: Dark/neon styled modal providing seamless "Sign In" and "Create Account" workflows.
4. **Header Profile Pill**: Displays dynamic user avatar and email, with a one-click "Sign Out" button.
5. **Unauthorized Interceptor**: Emits `auth:unauthorized` when encountering a `401 Unauthorized` to seamlessly prompt user re-authentication.

---

## 9. Verification & Testing

Run the full authentication and isolation test suite:
```bash
pytest backend/tests/test_auth_and_isolation.py -v
```

Run complete project regression suite:
```bash
pytest backend/tests/ -v
```
