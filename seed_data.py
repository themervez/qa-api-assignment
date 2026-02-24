import requests
import json
import sys

BASE_URL = "http://localhost:8000"

# Sample users with various test scenarios
sample_users = [
    # Standard users
    {
        "username": "john_doe",
        "email": "john@example.com",
        "password": "password123",
        "age": 30,
        "phone": "+15551234567",
    },
    {
        "username": "jane_smith",
        "email": "jane@example.com",
        "password": "securepass456",
        "age": 25,
        "phone": "+14155551234",
    },
    {
        "username": "bob_wilson",
        "email": "bob@example.com",
        "password": "mypass789",
        "age": 35,
    },
    # Edge case users
    {
        "username": "alice_johnson",
        "email": "alice@example.com",
        "password": "alicepass",
        "age": 28,
        "phone": "+12125551234",
    },
    {
        "username": "charlie_brown",
        "email": "charlie@example.com",
        "password": "charlie123",
        "age": 22,
    },
    # Users with special characters (for testing validation)
    {
        "username": "test_user",
        "email": "test.user@example.com",
        "password": "Test@123",
        "age": 40,
    },
    {
        "username": "admin_user",
        "email": "admin@company.com",
        "password": "Admin@2024",
        "age": 45,
        "phone": "+19175551234",
    },
    # Boundary test users
    {
        "username": "max_age",
        "email": "maxage@example.com",
        "password": "maxage123",
        "age": 150,  # Maximum allowed age
    },
    {
        "username": "min_age",
        "email": "minage@example.com",
        "password": "minage123",
        "age": 18,  # Minimum allowed age
    },
    # User with long username (near max length)
    {
        "username": "very_long_username_that_is_close_to_fifty_chars",
        "email": "longuser@example.com",
        "password": "longpass123",
        "age": 30,
    },
]


def check_api_health():
    """Check if API is running before seeding"""
    try:
        response = requests.get(f"{BASE_URL}/")
        if response.status_code == 200:
            return True
    except requests.ConnectionError:
        return False
    return False


def seed_database():
    """Seed the database with sample users"""

    # Check if API is running
    if not check_api_health():
        print("Error: API is not running. Please start the server first.")
        print("Run: uvicorn main:app --reload --host 0.0.0.0 --port 8000")
        sys.exit(1)

    print("Seeding database with sample users...")
    print("-" * 50)

    success_count = 0
    failed_count = 0

    for user in sample_users:
        try:
            response = requests.post(f"{BASE_URL}/users", json=user)
            if response.status_code == 201:
                print(f"✓ Created user: {user['username']}")
                success_count += 1
            else:
                print(f"✗ Failed to create user: {user['username']}")
                print(f"  Status: {response.status_code}")
                print(f"  Error: {response.text}")
                failed_count += 1
        except Exception as e:
            print(f"✗ Error creating user {user['username']}: {e}")
            failed_count += 1

    print("-" * 50)
    print(f"\nDatabase seeding completed!")
    print(f"Successfully created: {success_count} users")
    print(f"Failed: {failed_count} users")

    if success_count > 0:
        print("\nSample credentials for testing:")
        print("-" * 30)
        print("Standard users:")
        print("  Username: john_doe, Password: password123")
        print("  Username: jane_smith, Password: securepass456")
        print("\nAdmin user:")
        print("  Username: admin_user, Password: Admin@2024")
        print("\nTest user:")
        print("  Username: test_user, Password: Test@123")

    return success_count, failed_count


def clear_database():
    """Optional: Clear existing users (would need an endpoint)"""
    print("Note: Clear database functionality not implemented")
    print("Users will accumulate if script is run multiple times")


if __name__ == "__main__":
    # Parse command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "--clear":
        clear_database()

    # Seed the database
    success, failed = seed_database()

    # Exit with appropriate code
    sys.exit(0 if failed == 0 else 1)
