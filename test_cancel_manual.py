#!/usr/bin/env python3
"""
Manual test runner for cancel feature.
This script tests the core functionality without requiring pytest.
"""
import asyncio
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from avap_bot.utils.cancel_registry import CancelRegistry
from avap_bot.utils.cancel_helpers import (
    cooperative_checkpoint,
    safe_network_call,
    register_user_task,
    CancellableOperation
)


async def test_basic_functionality():
    """Test basic cancel registry functionality."""
    print("🧪 Testing basic functionality...")
    
    registry = CancelRegistry()
    user_id = 12345
    
    # Test task registration
    async def test_task():
        try:
            for i in range(5):
                await cooperative_checkpoint(user_id, registry)
                await asyncio.sleep(0.1)
            return "completed"
        except asyncio.CancelledError:
            return "cancelled"
    
    task = asyncio.create_task(test_task())
    await registry.register_task(user_id, task)
    
    # Cancel after a short delay
    await asyncio.sleep(0.3)
    await registry.request_cancel(user_id)
    
    # Wait for task to complete
    result = await task
    print(f"✅ Task result: {result}")
    
    # Test cancellation status
    is_cancelled = await registry.is_cancel_requested(user_id)
    print(f"✅ Cancellation requested: {is_cancelled}")
    
    return result == "cancelled"


async def test_context_manager():
    """Test context manager functionality."""
    print("🧪 Testing context manager...")
    
    registry = CancelRegistry()
    user_id = 12345
    cleanup_called = False
    
    def cleanup():
        nonlocal cleanup_called
        cleanup_called = True
    
    try:
        async with CancellableOperation(registry, user_id, "test_op") as op:
            op.add_cleanup(cleanup)
            # Request cancellation
            await registry.request_cancel(user_id)
            # This should raise CancelledError
            await op.checkpoint()
    except asyncio.CancelledError:
        print("✅ Operation was cancelled as expected")
    
    print(f"✅ Cleanup called: {cleanup_called}")
    return cleanup_called


async def test_safe_network_call():
    """Test safe network call functionality."""
    print("🧪 Testing safe network call...")
    
    registry = CancelRegistry()
    user_id = 12345
    
    async def mock_network_call():
        await asyncio.sleep(0.1)
        return "network_success"
    
    # Test normal completion
    result = await safe_network_call(mock_network_call(), user_id, registry)
    print(f"✅ Network call result: {result}")
    
    # Test cancellation
    async def cancelled_network_call():
        await asyncio.sleep(0.1)
        await registry.request_cancel(user_id)
        return "network_success"
    
    try:
        await safe_network_call(cancelled_network_call(), user_id, registry)
        print("❌ Expected cancellation but got success")
        return False
    except asyncio.CancelledError:
        print("✅ Network call was cancelled as expected")
        return True


async def test_multiple_tasks():
    """Test cancelling multiple tasks."""
    print("🧪 Testing multiple tasks cancellation...")
    
    registry = CancelRegistry()
    user_id = 12345
    
    async def create_task(task_id):
        try:
            for i in range(3):
                await cooperative_checkpoint(user_id, registry)
                await asyncio.sleep(0.1)
            return f"task_{task_id}_completed"
        except asyncio.CancelledError:
            return f"task_{task_id}_cancelled"
    
    # Create multiple tasks
    tasks = []
    for i in range(3):
        task = asyncio.create_task(create_task(i))
        await registry.register_task(user_id, task)
        tasks.append(task)
    
    # Cancel all tasks
    await asyncio.sleep(0.2)
    stats = await registry.cancel_all_for_user(user_id)
    
    # Wait for all tasks
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    print(f"✅ Cancellation stats: {stats}")
    print(f"✅ Task results: {results}")
    
    # Check that all tasks were cancelled
    all_cancelled = all("cancelled" in str(result) for result in results)
    print(f"✅ All tasks cancelled: {all_cancelled}")
    
    return all_cancelled and stats['tasks_cancelled'] == 3


async def main():
    """Run all tests."""
    print("🚀 Starting cancel feature tests...\n")
    
    tests = [
        test_basic_functionality,
        test_context_manager,
        test_safe_network_call,
        test_multiple_tasks
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            result = await test()
            if result:
                passed += 1
                print("✅ Test passed\n")
            else:
                print("❌ Test failed\n")
        except Exception as e:
            print(f"❌ Test failed with exception: {e}\n")
    
    print(f"📊 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Cancel feature is working correctly.")
        return 0
    else:
        print("⚠️ Some tests failed. Please check the implementation.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
