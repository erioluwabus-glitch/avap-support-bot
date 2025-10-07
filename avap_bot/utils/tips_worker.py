"""
Worker function for adding default tips in a separate process.
This prevents memory spikes in the main application process.
"""
import os
import logging
from datetime import datetime, timezone

# Set up logging for worker process
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def add_default_tips_worker():
    """
    Worker function to add default tips in a separate process.
    This function will be called by the background process utility.
    """
    try:
        logger.info("Worker process: Starting default tips initialization...")
        
        # Import heavy libraries only when needed
        from avap_bot.services.sheets_service import get_manual_tips, append_tip
        
        # Check if tips already exist
        tips = get_manual_tips()
        
        if not tips:
            logger.info("Worker process: No manual tips found, adding default tips...")
            
            default_tips = [
                {
                    'content': '💡 Remember: Consistency is key to success! Keep working on your goals every day.',
                    'type': 'manual',
                    'added_by': 'system',
                    'added_at': datetime.now(timezone.utc)
                },
                {
                    'content': '🎯 Set small, achievable goals for today. Progress is made one step at a time.',
                    'type': 'manual',
                    'added_by': 'system',
                    'added_at': datetime.now(timezone.utc)
                },
                {
                    'content': '📚 Learning is a journey, not a destination. Enjoy the process and celebrate your progress.',
                    'type': 'manual',
                    'added_by': 'system',
                    'added_at': datetime.now(timezone.utc)
                },
                {
                    'content': '🔥 Don\'t wait for motivation - create it! Start with small actions and build momentum.',
                    'type': 'manual',
                    'added_by': 'system',
                    'added_at': datetime.now(timezone.utc)
                },
                {
                    'content': '🌟 Every expert was once a beginner. Your current struggles are building your future expertise.',
                    'type': 'manual',
                    'added_by': 'system',
                    'added_at': datetime.now(timezone.utc)
                },
                {
                    'content': '⏰ Time management tip: Use the Pomodoro technique - 25 minutes focused work, 5 minutes break.',
                    'type': 'manual',
                    'added_by': 'system',
                    'added_at': datetime.now(timezone.utc)
                },
                {
                    'content': '🚀 Break complex tasks into smaller, manageable steps. Each step forward is progress.',
                    'type': 'manual',
                    'added_by': 'system',
                    'added_at': datetime.now(timezone.utc)
                }
            ]
            
            # Add tips one by one (batch operations can be added later)
            for tip_data in default_tips:
                try:
                    success = append_tip(tip_data['content'], tip_data['type'], tip_data['added_by'])
                    if success:
                        logger.info(f"Worker process: Added default tip: {tip_data['content'][:50]}...")
                    else:
                        logger.warning(f"Worker process: Failed to add default tip: {tip_data['content'][:50]}...")
                except Exception as e:
                    logger.exception(f"Worker process: Error adding default tip: {e}")
            
            logger.info(f"Worker process: Added {len(default_tips)} default tips to the system")
        else:
            logger.info(f"Worker process: Found {len(tips)} existing manual tips, skipping default tips")
            
    except Exception as e:
        logger.exception(f"Worker process: Failed to ensure manual tips: {e}")
        raise

if __name__ == "__main__":
    # Allow running this worker directly for testing
    add_default_tips_worker()
