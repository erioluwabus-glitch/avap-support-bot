def check_verified_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Check if user is verified"""
    try:
        client = get_supabase()
        logger.info(f"Checking verification for telegram_id: {telegram_id}")
        
        res = client.table('verified_users') \
                   .select('*') \
                   .eq('telegram_id', telegram_id) \
                   .eq('status', 'verified') \
                   .execute()
                   
        if res.data and len(res.data) > 0:
            logger.info(f"User {telegram_id} is verified")
            return res.data[0]
        
        logger.info(f"User {telegram_id} is not verified")
        return None
        
    except Exception as e:
        logger.error(f"Error checking verification: {str(e)}")
        return None