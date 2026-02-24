# User Management API

##  Overview

A FastAPI-based User Management system with RESTful endpoints for user operations.

##  Quick Start

### Prerequisites
- Python 3.10+
- pip

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd qa-assignment
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Start the API server**
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

4. **Seed sample data** (optional)
   ```bash
   python3 seed_data.py 
   ```

## 📚 Documentation

- **Assignment Instructions**: See [QA_ASSIGNMENT.md](QA_ASSIGNMENT.md)
- **API Documentation**: http://localhost:8000/docs
- **Alternative Docs**: http://localhost:8000/redoc

## 🔗 API Endpoints

### Public Endpoints
- `GET /` - API information
- `POST /users` - Create new user
- `GET /users` - List users
- `GET /users/{id}` - Get user by ID
- `POST /login` - User authentication

### Protected Endpoints
- `PUT /users/{id}` - Update user
- `DELETE /users/{id}` - Delete user

### Additional Endpoints
- `GET /users/search` - Search users
- `GET /stats` - System statistics
- `GET /health` - Health check

## 🗂 Project Structure

```
qa-assignment/
├── main.py              # FastAPI application
├── seed_data.py         # Sample data generator
├── requirements.txt     # Python dependencies
├── QA_ASSIGNMENT.md     # Assignment details
└── README.md           # This file
```

##  For QA Engineers

Your task is to:
1. Test all API endpoints thoroughly
2. Identify and document bugs
3. Write automated tests
4. Create comprehensive test reports

See [QA_ASSIGNMENT.md](QA_ASSIGNMENT.md) for detailed instructions.

##  Sample Credentials

After running `seed_data.py`:
- Username: `john_doe`, Password: `password123`
- Username: `jane_smith`, Password: `securepass456`

---

**Good luck with your assignment!** 