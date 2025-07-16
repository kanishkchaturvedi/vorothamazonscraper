#!/usr/bin/env python3
"""
Health check script to verify Crawl4AI database path and permissions.
"""
import os
import tempfile
import sys

def check_database_path():
    """Check if the database path is accessible and writable."""
    db_path = os.environ.get('CRAWL4AI_DB_PATH', '/app/crawl4ai_db')
    
    # Check if path exists
    if not os.path.exists(db_path):
        try:
            os.makedirs(db_path, exist_ok=True)
            print(f"✓ Created database directory: {db_path}")
        except Exception as e:
            print(f"✗ Failed to create database directory: {e}")
            return False
    
    # Check if path is writable
    try:
        test_file = os.path.join(db_path, 'test_write.tmp')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        print(f"✓ Database directory is writable: {db_path}")
        return True
    except Exception as e:
        print(f"✗ Database directory is not writable: {e}")
        return False

def check_home_directory():
    """Check if home directory is accessible."""
    home_path = os.environ.get('HOME', '/home/appuser')
    
    if not os.path.exists(home_path):
        print(f"✗ Home directory does not exist: {home_path}")
        return False
    
    # Check if writable
    try:
        test_file = os.path.join(home_path, 'test_write.tmp')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        print(f"✓ Home directory is writable: {home_path}")
        return True
    except Exception as e:
        print(f"✗ Home directory is not writable: {e}")
        return False

def main():
    """Run all health checks."""
    print("Running Docker health checks...")
    
    # Check current user
    print(f"Current user: {os.getenv('USER', 'unknown')}")
    print(f"Current UID: {os.getuid()}")
    print(f"Current GID: {os.getgid()}")
    
    # Check paths
    checks = [
        check_database_path(),
        check_home_directory()
    ]
    
    if all(checks):
        print("✓ All health checks passed")
        return 0
    else:
        print("✗ Some health checks failed")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 