# Universal /cancel Command Feature

## Overview

This feature implements a robust, universal `/cancel` command for the AVAP Telegram bot that allows users to immediately stop any ongoing operations (conversations, background tasks, uploads/transcriptions, matching, broadcasts, scheduled per-user jobs) in a safe, consistent, and testable way.

## Architecture

### Core Components

1. **`CancelRegistry`** (`utils/cancel_registry.py`) - Thread-safe registry for managing user task and job cancellations
2. **Cancel Helpers** (`utils/cancel_helpers.py`) - Decorators and context managers for cooperative cancellation
3. **Cancel Feature** (`features/cancel_feature.py`) - Command handlers and integration logic
4. **Unit Tests** (`tests/test_cancel_registry.py`) - Comprehensive test coverage

### Key Features

- **Cooperative Cancellation**: Long-running operations check for cancellation at regular intervals
- **Immediate Task Cancellation**: Uses asyncio task cancellation for responsive user experience
- **Admin Override**: Admins can cancel other users' operations with `/cancel <user_id>`
- **Conversation Integration**: All conversation handlers support `/cancel` as a fallback
- **Background Task Support**: Tracks and cancels background tasks and scheduled jobs
- **Comprehensive Logging**: Detailed logging for debugging and monitoring

## Usage

### For Users

#### Basic Cancellation
```
/cancel
```
Cancels all ongoing operations for the current user.

#### Admin Cancellation
```
/cancel <user_id>
```
Admins can cancel operations for any user by providing their Telegram user ID.

### For Developers

#### Registering Tasks
```python
from avap_bot.utils.cancel_helpers import register_user_task

async with register_user_task(cancel_registry, user_id):
    # Long-running operation here
    await some_long_operation()
```

#### Cooperative Checkpoints
```python
from avap_bot.utils.cancel_helpers import cooperative_checkpoint

for item in items:
    await cooperative_checkpoint(user_id, cancel_registry)
    await process_item(item)
```

#### Safe Network Calls
```python
from avap_bot.utils.cancel_helpers import safe_network_call

result = await safe_network_call(
    some_network_operation(),
    user_id,
    cancel_registry
)
```

#### Context Manager for Operations
```python
from avap_bot.utils.cancel_helpers import CancellableOperation

async with CancellableOperation(cancel_registry, user_id, "operation_name") as op:
    # Add cleanup callbacks
    op.add_cleanup(lambda: cleanup_function())
    
    # Check for cancellation at checkpoints
    await op.checkpoint()
    
    # Operation logic here
```

## Implementation Details

### CancelRegistry API

```python
class CancelRegistry:
    async def register_task(self, user_id: int, task: asyncio.Task) -> None
    async def unregister_task(self, user_id: int, task: asyncio.Task) -> None
    async def register_job(self, user_id: int, cancel_callable: Callable) -> str
    async def unregister_job(self, user_id: int, job_token: str) -> None
    async def request_cancel(self, user_id: int) -> None
    async def cancel_all_for_user(self, user_id: int) -> Dict[str, int]
    async def is_cancel_requested(self, user_id: int) -> bool
    async def clear_user(self, user_id: int) -> None
```

### Integration Points

#### Bot Integration
The cancel registry is initialized in `bot.py` and stored in `bot_app.bot_data['cancel_registry']` for access by all handlers.

#### Conversation Handler Integration
All conversation handlers now include the cancel fallback:
```python
ConversationHandler(
    entry_points=[...],
    states={...},
    fallbacks=[get_cancel_fallback_handler()],
    per_message=True  # Important for proper cancel handling
)
```

#### Handler Registration
```python
# In bot.py
from avap_bot.features.cancel_feature import register_cancel_handlers
register_cancel_handlers(bot_app)
```

## Testing

### Unit Tests
Run the comprehensive test suite:
```bash
python -m pytest tests/test_cancel_registry.py -v
```

### Manual Testing

#### Test Long-Running Operations
1. Start the bot in development mode
2. Use the test command: `/longop`
3. While the operation is running, send `/cancel`
4. Verify the operation stops within 2 seconds

#### Test Conversation Cancellation
1. Start any conversation (e.g., `/start` for verification)
2. Send `/cancel` during the conversation
3. Verify the conversation ends and user sees cancellation message

#### Test Admin Cancellation
1. Have an admin user send `/cancel <user_id>` for another user
2. Verify the target user's operations are cancelled
3. Verify the target user receives a notification

## Configuration

### Environment Variables

- `ADMIN_USER_IDS`: Comma-separated list of admin user IDs (optional, falls back to `ADMIN_USER_ID`)
- `ADMIN_USER_ID`: Single admin user ID (fallback if `ADMIN_USER_IDS` not set)
- `ENVIRONMENT`: Set to "development" to enable test commands

### Admin Permissions

Admins are determined by checking if the user's ID is in the `ADMIN_USER_IDS` environment variable or matches `ADMIN_USER_ID`.

## Safety & Limitations

### What Can Be Cancelled
- ✅ Asyncio tasks (immediate cancellation)
- ✅ Conversation flows (immediate exit)
- ✅ Background jobs with registered cancel callbacks
- ✅ Long-running loops with cooperative checkpoints
- ✅ Network operations wrapped with `safe_network_call`

### What Cannot Be Cancelled
- ❌ Blocking synchronous operations (must be converted to async)
- ❌ OS-level processes (would require process management)
- ❌ Third-party blocking functions (must be run in executor)

### Graceful Degradation
If cancellation cannot be achieved immediately, the system:
1. Marks cancellation as requested
2. Attempts to cancel registered tasks
3. Calls registered job cancel callbacks
4. Logs any remaining active operations
5. Notifies admins of any issues

## Monitoring & Debugging

### Logs to Watch
- `CancelRegistry initialized` - System startup
- `Cancel requested for user X` - Cancellation requests
- `Cancellation completed for user X` - Successful cancellations
- `⚠️ Cancellation Warning` - Issues with cancellation

### Admin Notifications
Admins receive notifications when:
- Cancellation fails for a user
- Tasks remain active after cancellation attempt
- Errors occur during cancellation process

## Migration Guide

### For Existing Handlers
1. Import the cancel fallback: `from avap_bot.features.cancel_feature import get_cancel_fallback_handler`
2. Replace lambda cancel handlers with: `fallbacks=[get_cancel_fallback_handler()]`
3. Add cooperative checkpoints in long-running operations
4. Register background tasks with the cancel registry

### For New Features
1. Use the provided context managers and decorators
2. Add cooperative checkpoints in loops
3. Register any background tasks or jobs
4. Test cancellation scenarios

## Performance Considerations

- **Minimal Overhead**: Registry operations are O(1) for most operations
- **Memory Efficient**: Automatic cleanup of completed tasks
- **Non-Blocking**: All operations are async and don't block the event loop
- **Scalable**: Supports unlimited users and tasks per user

## Security Considerations

- **Admin-Only Override**: Only admins can cancel other users' operations
- **User Isolation**: Users can only cancel their own operations
- **Audit Trail**: All cancellations are logged with user IDs and timestamps
- **Safe Cleanup**: Cleanup functions are called even if cancellation fails

## Future Enhancements

- **Process Management**: Add support for cancelling OS-level processes
- **Cancellation Timeouts**: Configurable timeouts for different operation types
- **Cancellation Reasons**: Allow users to specify why they're cancelling
- **Bulk Operations**: Cancel operations for multiple users at once
- **Cancellation History**: Track and display cancellation history for admins
