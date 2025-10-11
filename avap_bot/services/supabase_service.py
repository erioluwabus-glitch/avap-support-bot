"""
Supabase service for database operations
"""
import os
import logging
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from supabase import create_client, Client

logger = logging.getLogger(__name__)

def _get_response_data(response):
    """Get data from Supabase response, handling different API versions"""
    if response is None:
        return None

    # Try new API format first (no .data attribute needed)
    if hasattr(response, 'data'):
        return response.data

    # Fallback to direct access for newer API
    try:
        # In newer Supabase API, response might be the data directly
        if isinstance(response, list):
            return response
        elif isinstance(response, dict) and 'data' in response:
            return response['data']
        else:
            return response
    except:
        return response

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Global client instance
supabase_client: Optional[Client] = None


def _clean_supabase_url(url: str) -> str:
    """Validate and clean Supabase URL format"""
    if not url:
        raise ValueError("SUPABASE_URL is required")
    
    # Strip any trailing slashes
    cleaned_url = url.rstrip('/')
    
    if not cleaned_url.startswith('https://'):
        cleaned_url = f"https://{cleaned_url}"
    
    if not cleaned_url.endswith('.supabase.co'):
        raise ValueError("Invalid Supabase URL format")
    
    return cleaned_url


def validate_supabase_credentials():
    """Validate Supabase credentials"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
    
    if not SUPABASE_KEY.startswith('eyJ'):
        raise ValueError("Invalid Supabase key format")
    
    if len(SUPABASE_KEY) < 100:
        raise ValueError("Supabase key appears to be too short")


def check_tables_exist():
    """Check if all required tables exist"""
    required_tables = ['verified_users', 'pending_verifications', 'match_requests']

    for table in required_tables:
        try:
            client = get_supabase()
            # Use newer Supabase API with .execute()
            try:
                client.table(table).select('*').limit(1).execute()
            except AttributeError:
                # Fallback for older API
                client.table(table).select('*').limit(1).execute()
        except Exception as e:
            logger.warning(f"Table {table} may not exist: {e}")


def init_supabase() -> Client:
    """Initialize Supabase client (lightweight - no heavy operations during startup)"""
    global supabase_client

    if supabase_client:
        return supabase_client

    try:
        validate_supabase_credentials()

        logger.info("🚀 Creating Supabase client (lightweight initialization)...")
        # Create client without heavy connection test during startup
        test_client = create_client(SUPABASE_URL, SUPABASE_KEY)

        # Store client - connection test will happen on first actual use via get_supabase()
        supabase_client = test_client
        logger.info("✅ Supabase client created (connection test deferred until first use)")
        return supabase_client

    except Exception as e:
        logger.error(f"❌ Supabase client creation failed: {str(e)}")
        raise


def get_supabase() -> Client:
    """Get or initialize Supabase client with connection check"""
    global supabase_client
    if supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
        logger.info("Creating Supabase client for first use...")
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

        # Do connection test on first use
        try:
            supabase_client.table('verified_users').select('count', count='exact').limit(1).execute()
            logger.info("✅ Supabase connection test successful")
        except Exception as e:
            logger.error(f"❌ Supabase connection test failed: {str(e)}")
            raise

    return supabase_client


def add_pending_verification(data: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a row into pending_verifications"""
    client = get_supabase()
    try:
        logger.debug(f"Attempting to add pending verification for: {data.get('email', 'unknown')}")

        # First try with status column
        insert_data = {
            'name': data.get('name'),
            'email': data.get('email'),
            'phone': data.get('phone'),
            'status': data.get('status', 'Pending')
        }

        logger.debug(f"Insert data: {insert_data}")

        try:
            res = client.table("pending_verifications").insert(insert_data).execute()
            # Handle different response formats
            response_data = _get_response_data(res)
            if response_data:
                logger.info(f"Added pending verification: {response_data[0].get('name', 'Unknown') if response_data else 'Unknown'}")
                return response_data[0] if response_data else None
            else:
                logger.error("No data returned from insert operation")
                raise Exception("No data returned from insert")

        except Exception as status_error:
            logger.warning(f"Status column error: {status_error}")
            # If status column doesn't exist, try without it
            if "status" in str(status_error) and "column" in str(status_error).lower():
                logger.warning("Status column not found, inserting without status field")
                insert_data_without_status = {
                    'name': data.get('name'),
                    'email': data.get('email'),
                    'phone': data.get('phone')
                }
                res = client.table("pending_verifications").insert(insert_data_without_status).execute()
                if res:
                    response_data = _get_response_data(res)
                    if response_data:
                        logger.info(f"Added pending verification: {response_data[0].get('name', 'Unknown')}")
                        return response_data[0] if response_data else None
                    else:
                        logger.error("No data returned from insert operation without status")
                        raise Exception("No data returned from insert")
                else:
                    logger.error("Insert operation returned no response")
                    raise status_error
            else:
                # Re-raise the original error if it's not a column issue
                raise status_error

    except Exception as e:
        logger.error(f"❌ Error adding pending verification: {str(e)}")
        logger.error(f"Data that failed to insert: {data}")
        logger.error("Possible causes:")
        logger.error("1. Connection issues with Supabase")
        logger.error("2. Table 'pending_verifications' doesn't exist")
        logger.error("3. Required columns (name, email, phone) don't exist")
        logger.error("4. Invalid data types or constraints")
        raise


def find_verified_by_telegram(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Find verified user by telegram ID"""
    try:
        client = get_supabase()
        res = client.table("verified_users").select("*").eq("telegram_id", telegram_id).eq("status", "verified").execute()
        data = _get_response_data(res)
        if data and len(data) > 0:
            return data[0]
        return None
    except Exception as e:
        logger.exception("Supabase find_verified_by_telegram error: %s", e)
        return None


def find_pending_by_email_or_phone(email: Optional[str] = None, phone: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search pending_verifications by email or phone"""
    try:
        client = get_supabase()
        results = []

        if email:
            res = client.table("pending_verifications").select("*").eq("email", email).execute()
            data = _get_response_data(res)
            if data:
                results.extend(data or [])

        if phone:
            res = client.table("pending_verifications").select("*").eq("phone", phone).execute()
            data = _get_response_data(res)
            if data:
                results.extend(data or [])

        return results
    except Exception as e:
        logger.exception("Supabase find_pending_by_email_or_phone error: %s", e)
        return []


def find_pending_by_name(name: str) -> List[Dict[str, Any]]:
    """Search pending_verifications by name"""
    try:
        client = get_supabase()
        res = client.table("pending_verifications").select("*").eq("name", name).execute()
        data = _get_response_data(res)
        return data or []
    except Exception as e:
        logger.exception("Supabase find_pending_by_name error: %s", e)
        return []


def find_verified_by_email_or_phone(email: Optional[str] = None, phone: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search verified_users by email or phone"""
    try:
        client = get_supabase()
        results = []

        if email:
            res = client.table("verified_users").select("*").eq("email", email).eq("status", "verified").execute()
            data = _get_response_data(res)
            if data:
                results.extend(data or [])

        if phone:
            res = client.table("verified_users").select("*").eq("phone", phone).eq("status", "verified").execute()
            data = _get_response_data(res)
            if data:
                results.extend(data or [])

        return results
    except Exception as e:
        logger.exception("Supabase find_verified_by_email_or_phone error: %s", e)
        return []


def find_verified_by_name(name: str) -> List[Dict[str, Any]]:
    """Search verified_users by name (case-insensitive)"""
    client = get_supabase()
    try:
        res = client.table("verified_users").select("*").ilike("name", f"%{name}%").eq("status", "verified").execute()
        data = _get_response_data(res)
        return data or []
    except Exception as e:
        logger.exception("Supabase find_verified_by_name error: %s", e)
        return []


async def promote_pending_to_verified(pending_id: int, telegram_id: int) -> Dict[str, Any]:
    """Promote pending verification to verified user"""
    client = get_supabase()
    try:
        # Fetch pending row
        r = client.table("pending_verifications").select("*").eq("id", pending_id).execute()
        if not r.data:
            raise Exception("Pending verification not found")

        row = r.data[0]
        logger.info(f"Promoting user: {row['name']} ({row['email']}) from pending to verified")

        verified_payload = {
            "name": row["name"],
            "email": row["email"],
            "phone": row["phone"],
            "telegram_id": telegram_id,
            "status": "verified"
        }

        logger.info(f"Inserting verified user payload: {verified_payload}")
        ins = client.table("verified_users").insert(verified_payload).execute()
        if not ins.data:
            logger.error("Failed to insert verified user - no data returned")
            raise Exception("Failed to insert verified user")

        verified_user = ins.data[0]
        logger.info(f"Successfully inserted verified user: {verified_user['name']} ({verified_user['email']})")

        # Note: Systeme.io contact already created with verified status when student was added

        # Optionally delete pending row:
        client.table("pending_verifications").delete().eq("id", pending_id).execute()
        return verified_user
    except Exception as e:
        logger.exception("Supabase promote_pending_to_verified error: %s", e)
        raise


def remove_verified_user(identifier: str) -> bool:
    """Identifier may be email, phone, or full name. Return True if deleted."""
    client = get_supabase()
    try:
        # First, check if user exists in verified_users
        user_exists = False
        user_info = None
        table_name = "verified_users"
        
        # Check by email
        res = client.table("verified_users").select("*").eq("email", identifier).execute()
        data = _get_response_data(res)
        if data:
            user_exists = True
            user_info = data[0]
            table_name = "verified_users"
            logger.info(f"Found user by email in verified_users: {identifier}")
        else:
            # Check by phone
            res = client.table("verified_users").select("*").eq("phone", identifier).execute()
            data = _get_response_data(res)
            if data:
                user_exists = True
                user_info = data[0]
                table_name = "verified_users"
                logger.info(f"Found user by phone in verified_users: {identifier}")
            else:
                # Check by name
                res = client.table("verified_users").select("*").eq("name", identifier).execute()
                data = _get_response_data(res)
                if data:
                    user_exists = True
                    user_info = data[0]
                    table_name = "verified_users"
                    logger.info(f"Found user by name in verified_users: {identifier}")
        
        # If not found in verified_users, check pending_verifications
        if not user_exists:
            # Check by email in pending_verifications
            res = client.table("pending_verifications").select("*").eq("email", identifier).execute()
            data = _get_response_data(res)
            if data:
                user_exists = True
                user_info = data[0]
                table_name = "pending_verifications"
                logger.info(f"Found user by email in pending_verifications: {identifier}")
            else:
                # Check by phone in pending_verifications
                res = client.table("pending_verifications").select("*").eq("phone", identifier).execute()
                data = _get_response_data(res)
                if data:
                    user_exists = True
                    user_info = data[0]
                    table_name = "pending_verifications"
                    logger.info(f"Found user by phone in pending_verifications: {identifier}")
                else:
                    # Check by name in pending_verifications
                    res = client.table("pending_verifications").select("*").eq("name", identifier).execute()
                    data = _get_response_data(res)
                    if data:
                        user_exists = True
                        user_info = data[0]
                        table_name = "pending_verifications"
                        logger.info(f"Found user by name in pending_verifications: {identifier}")
        
        if not user_exists:
            logger.warning(f"User not found for identifier: {identifier}")
            logger.warning(f"Searched by email, phone, and name in both verified_users and pending_verifications - no matches found")
            logger.info(f"This is normal if the user was never added or already removed")
            return False
        
        # Now delete the user from the appropriate table
        if user_info:
            # Delete by the primary key or unique identifier
            if user_info.get('email'):
                res = client.table(table_name).delete().eq("email", user_info['email']).execute()
            elif user_info.get('phone'):
                res = client.table(table_name).delete().eq("phone", user_info['phone']).execute()
            else:
                res = client.table(table_name).delete().eq("name", user_info['name']).execute()
            
            data = _get_response_data(res)
            if data:
                logger.info(f"Successfully removed user from {table_name}: {identifier}")
                return True
            else:
                logger.error(f"Failed to delete user record from {table_name}: {identifier}")
                return False
        else:
            logger.error(f"No user info found for deletion: {identifier}")
            return False
            
    except Exception as e:
        logger.exception("Supabase remove_verified_user error: %s", e)
        return False


def remove_verified_by_identifier(identifier: str) -> bool:
    """Alias for remove_verified_user for backward compatibility"""
    return remove_verified_user(identifier)


def get_all_verified_users() -> List[Dict[str, Any]]:
    """Get all verified users"""
    client = get_supabase()
    try:
        res = client.table("verified_users").select("*").eq("status", "verified").execute()
        data = _get_response_data(res)
        return data or []
    except Exception as e:
        logger.exception("Supabase get_all_verified_users error: %s", e)
        return []


def add_match_request(telegram_id: int, username: str) -> str:
    """Add match request and return match_id"""
    logger.info(f"Adding match request for telegram_id: {telegram_id}, username: {username}")
    client = get_supabase()
    match_id = str(uuid.uuid4())
    payload = {
        "match_id": match_id,
        "telegram_id": telegram_id,
        "username": username,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    try:
        logger.info(f"Inserting match request with payload: {payload}")
        res = client.table("match_requests").insert(payload).execute()
        logger.info(f"Successfully added match request with ID: {match_id}")
        return match_id
    except Exception as e:
        # If username column doesn't exist, try without it
        if "username" in str(e) and "column" in str(e).lower():
            logger.warning("Username column not found in match_requests, inserting without username field")
            payload_without_username = {
                "match_id": match_id,
                "telegram_id": telegram_id,
                "status": "pending",
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            res = client.table("match_requests").insert(payload_without_username)
            return match_id
        else:
            logger.exception("Supabase add_match_request error: %s", e)
            raise


def pop_match_request(exclude_id: int) -> Optional[Dict[str, Any]]:
    """Pop a match request excluding the given telegram_id"""
    logger.info(f"Searching for match requests excluding telegram_id: {exclude_id}")
    client = get_supabase()
    try:
        # Get a random pending request that's not from the same user
        res = client.table("match_requests").select("*").neq("telegram_id", exclude_id).eq("status", "pending").limit(1).execute()
        logger.info(f"Match request query returned {len(res.data) if res.data else 0} results")
        
        if not res.data:
            logger.info(f"No pending match requests found excluding user {exclude_id}")
            return None

        match_request = res.data[0]
        logger.info(f"Found match request: {match_request}")
        # Mark as matched
        client.table("match_requests").update({"status": "matched"}).eq("match_id", match_request["match_id"]).execute()
        logger.info(f"Marked match request {match_request['match_id']} as matched")
        return match_request
    except Exception as e:
        logger.exception("Supabase pop_match_request error: %s", e)
        return None


def clear_all_match_requests() -> bool:
    """Clear all match requests from the database"""
    logger.info("Clearing all match requests from database")
    client = get_supabase()
    try:
        # Delete all match requests
        res = client.table("match_requests").delete().neq("match_id", "").execute()
        logger.info(f"Successfully cleared all match requests")
        return True
    except Exception as e:
        logger.exception("Supabase clear_all_match_requests error: %s", e)
        return False


def check_verified_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Check if user is verified by telegram_id"""
    try:
        client = get_supabase()
        res = client.table("verified_users").select("*").eq("telegram_id", telegram_id).eq("status", "verified").execute()
        data = _get_response_data(res)
        if data and len(data) > 0:
            return data[0] if data else None
        return None
    except Exception as e:
        logger.exception("Supabase check_verified_user error: %s", e)
        return None


def get_student_questions(telegram_id: int) -> List[Dict[str, Any]]:
    """Get all questions for a student"""
    client = get_supabase()
    try:
        res = client.table("questions").select("*").eq("telegram_id", telegram_id).execute()
        data = _get_response_data(res)
        return data or []
    except Exception as e:
        logger.exception("Supabase get_student_questions error: %s", e)
        return []





def add_question(telegram_id: int, username: str, question_text: str, file_id: Optional[str] = None, file_name: Optional[str] = None, answer: Optional[str] = None, status: str = "pending") -> Dict[str, Any]:
    """Add a new question"""
    client = get_supabase()
    try:
        payload = {
            "telegram_id": telegram_id,
            "username": username,
            "question_text": question_text,
            "file_id": file_id,
            "file_name": file_name,
            "status": status,
            "asked_at": datetime.now(timezone.utc).isoformat()
        }

        # Only add answer if provided (for auto-answered questions)
        if answer:
            payload["answer"] = answer
            payload["answered_at"] = datetime.now(timezone.utc).isoformat()

        res = client.table("questions").insert(payload).execute()
        data = _get_response_data(res)
        return data[0] if data else None
    except Exception as e:
        logger.exception("Supabase add_question error: %s", e)
        raise


def get_student_questions(telegram_id: int) -> List[Dict[str, Any]]:
    """Get all questions for a student"""
    client = get_supabase()
    try:
        res = client.table("questions").select("*").eq("telegram_id", telegram_id).execute()
        data = _get_response_data(res)
        return data or []
    except Exception as e:
        logger.exception("Supabase get_student_questions error: %s", e)
        return []


def update_question_answer(question_id: int, answer: str) -> bool:
    """Update a question with an answer"""
    client = get_supabase()
    try:
        update_data = {
            "answer": answer,
            "status": "answered",
            "answered_at": datetime.now(timezone.utc).isoformat()
        }
        res = client.table("questions").update(update_data).eq("id", question_id).execute()
        data = _get_response_data(res)
        return bool(data)
    except Exception as e:
        logger.exception("Supabase update_question_answer error: %s", e)
        return False


def get_faqs() -> List[Dict[str, Any]]:
    """Get all FAQs"""
    client = get_supabase()
    try:
        res = client.table("faqs").select("*").execute()
        data = _get_response_data(res)
        return data or []
    except Exception as e:
        logger.exception("Supabase get_faqs error: %s", e)
        return []


def get_answered_questions() -> List[Dict[str, Any]]:
    """Get all answered questions"""
    try:
        client = get_supabase()
        res = client.table("questions").select("*").neq("answer", None).execute()
        data = _get_response_data(res)
        return data or []
    except Exception as e:
        logger.exception("Supabase get_answered_questions error: %s", e)
        return []


    client = get_supabase()
    try:
        payload = {
            "question": question,
            "answer": answer,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        res = client.table("faqs").insert(payload).execute()
        data = _get_response_data(res)
        return data[0] if data else None
    except Exception as e:
        logger.exception("Supabase add_faq error: %s", e)
        raise


    client = get_supabase()
    try:
        res = client.table("tips").select("*").eq("day_of_week", day_of_week).limit(1).execute()
        data = _get_response_data(res)
        return data[0] if data else None
    except Exception as e:
        logger.exception("Supabase get_tip_for_day error: %s", e)
        return None


    client = get_supabase()
    try:
        payload = {
            "content": content,
            "day_of_week": day_of_week,
            "tip_type": "manual",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        res = client.table("tips").insert(payload).execute()
        data = _get_response_data(res)
        return data[0] if data else None
    except Exception as e:
        logger.exception("Supabase add_manual_tip error: %s", e)
        raise


    client = get_supabase()
    
    # Get all verified users
    users_res = client.table("verified_users").select("*").eq("status", "verified")
    try:
        users = _get_response_data(users_res) or []
    except Exception as e:
        logger.exception("Supabase get_top_students error: %s", e)
        return []
    
    top_students = []
    for user in users:
        telegram_id = user.get("telegram_id")
        if not telegram_id:
            continue
        
        # Count assignments
        assignments_res = client.table("assignments").select("id", count="exact").eq("telegram_id", telegram_id).execute()
        assignment_count = assignments_res.count or 0
        
        # Count wins
        wins_res = client.table("wins").select("id", count="exact").eq("telegram_id", telegram_id).execute()
        wins_count = wins_res.count or 0
        
        if assignment_count >= 3 and wins_count >= 3:
            top_students.append({
                "telegram_id": telegram_id,
                "username": user.get("username", "unknown"),
                "name": user.get("name", "Unknown"),
                "assignments": assignment_count,
                "wins": wins_count,
                "joined_at": user.get("created_at", "Unknown")
            })
    
    return top_students


    client = get_supabase()
    try:
        res = client.table("verified_users").select("telegram_id").eq("status", "verified").execute()
        data = _get_response_data(res)
        return [user["telegram_id"] for user in (data or []) if user.get("telegram_id")]
    except Exception as e:
        logger.exception("Supabase get_all_verified_telegram_ids error: %s", e)
        return []


    client = get_supabase()
    try:
        res = client.table("verified_users").update({"badge": badge}).eq("telegram_id", telegram_id).execute()
        data = _get_response_data(res)
        return bool(data)
    except Exception as e:
        logger.exception("Supabase update_user_badge error: %s", e)
        return False


def get_assignment_by_id(assignment_id: str) -> Optional[Dict[str, Any]]:
    """Get assignment by ID"""
    client = get_supabase()
    try:
        res = client.table("assignments").select("*").eq("id", assignment_id).execute()
        data = _get_response_data(res)
        if data and len(data) > 0:
            return data[0] if data else None
        return None
    except Exception as e:
        logger.exception("Supabase get_assignment_by_id error: %s", e)
        return None


# Broadcast History Functions
def add_broadcast_history(admin_id: int, message_type: str, content: str, recipients_count: int, failures_count: int = 0) -> Dict[str, Any]:
    """Add broadcast to history"""
    client = get_supabase()
    try:
        payload = {
            "admin_id": admin_id,
            "message_type": message_type,
            "content": content,
            "recipients_count": recipients_count,
            "failures_count": failures_count,
            "sent_at": datetime.now(timezone.utc).isoformat()
        }
        res = client.table("broadcast_history").insert(payload).execute()
        data = _get_response_data(res)
        return data[0] if data else None
    except Exception as e:
        logger.exception("Supabase add_broadcast_history error: %s", e)
        raise


def get_broadcast_history(limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
    """Get broadcast history"""
    client = get_supabase()
    try:
        res = client.table("broadcast_history").select("*").order("sent_at", desc=True).limit(limit).offset(offset).execute()
        data = _get_response_data(res)
        return data or []
    except Exception as e:
        logger.exception("Supabase get_broadcast_history error: %s", e)
        return []


def delete_broadcast(broadcast_id: int) -> bool:
    """Delete broadcast from history"""
    client = get_supabase()
    try:
        res = client.table("broadcast_history").delete().eq("id", broadcast_id).execute()
        data = _get_response_data(res)
        return bool(data)
    except Exception as e:
        logger.exception("Supabase delete_broadcast error: %s", e)
        return False


# Tips Functions
def add_tip(text: str, created_by: int = None) -> Dict[str, Any]:
    """Add a new tip"""
    client = get_supabase()
    try:
        payload = {
            "text": text,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sent_count": 0
        }
        if created_by:
            payload["created_by"] = created_by
        res = client.table("tips").insert(payload).execute()
        data = _get_response_data(res)
        return data[0] if data else None
    except Exception as e:
        logger.exception("Supabase add_tip error: %s", e)
        raise


def get_all_tips() -> List[Dict[str, Any]]:
    """Get all tips"""
    client = get_supabase()
    try:
        res = client.table("tips").select("*").order("created_at", desc=True).execute()
        data = _get_response_data(res)
        return data or []
    except Exception as e:
        logger.exception("Supabase get_all_tips error: %s", e)
        return []


def get_random_tip() -> Optional[Dict[str, Any]]:
    """Get a random tip"""
    client = get_supabase()
    try:
        res = client.table("tips").select("*").execute()
        data = _get_response_data(res)
        if data:
            import random
            return random.choice(data)
        return None
    except Exception as e:
        logger.exception("Supabase get_random_tip error: %s", e)
        return None


def update_tip_sent_count(tip_id: int) -> bool:
    """Update tip sent count"""
    client = get_supabase()
    try:
        # First get current count
        res = client.table("tips").select("sent_count").eq("id", tip_id).execute()
        data = _get_response_data(res)
        if data:
            current_count = data[0].get("sent_count", 0)
            new_count = current_count + 1
            update_res = client.table("tips").update({"sent_count": new_count}).eq("id", tip_id).execute()
            return bool(_get_response_data(update_res))
        return False
    except Exception as e:
        logger.exception("Supabase update_tip_sent_count error: %s", e)
        return False


# Student Functions
def get_all_students() -> List[Dict[str, Any]]:
    """Get all verified students"""
    client = get_supabase()
    try:
        res = client.table("verified_users").select("*").eq("status", "verified").order("created_at", desc=True).execute()
        data = _get_response_data(res)
        return data or []
    except Exception as e:
        logger.exception("Supabase get_all_students error: %s", e)
        return []


def get_student_submissions_by_username(username: str) -> List[Dict[str, Any]]:
    """Get submissions by username"""
    client = get_supabase()
    try:
        res = client.table("assignments").select("*").eq("username", username).order("submitted_at", desc=True).execute()
        data = _get_response_data(res)
        return data or []
    except Exception as e:
        logger.exception("Supabase get_student_submissions_by_username error: %s", e)
        return []


def get_student_submissions_by_module(username: str, module: str) -> List[Dict[str, Any]]:
    """Get submissions by username and module"""
    client = get_supabase()
    try:
        res = client.table("assignments").select("*").eq("username", username).eq("module", module).order("submitted_at", desc=True).execute()
        data = _get_response_data(res)
        return data or []
    except Exception as e:
        logger.exception("Supabase get_student_submissions_by_module error: %s", e)
        return []


# Statistics Functions
def get_bot_statistics() -> Dict[str, Any]:
    """Get comprehensive bot statistics"""
    client = get_supabase()
    try:
        stats = {}
        
        # User counts
        total_users_res = client.table("verified_users").select("id", count="exact").execute()
        stats["total_users"] = total_users_res.count or 0
        
        verified_users_res = client.table("verified_users").select("id", count="exact").eq("status", "verified").execute()
        stats["verified_users"] = verified_users_res.count or 0
        
        # Submission stats
        total_submissions_res = client.table("assignments").select("id", count="exact").execute()
        stats["total_submissions"] = total_submissions_res.count or 0
        
        graded_submissions_res = client.table("assignments").select("id", count="exact").eq("status", "graded").execute()
        stats["graded_submissions"] = graded_submissions_res.count or 0
        
        pending_submissions_res = client.table("assignments").select("id", count="exact").eq("status", "submitted").execute()
        stats["pending_submissions"] = pending_submissions_res.count or 0
        
        # Win counts
        total_wins_res = client.table("wins").select("id", count="exact").execute()
        stats["total_wins"] = total_wins_res.count or 0
        
        # Question counts
        total_questions_res = client.table("questions").select("id", count="exact").execute()
        stats["total_questions"] = total_questions_res.count or 0
        
        answered_questions_res = client.table("questions").select("id", count="exact").eq("status", "answered").execute()
        stats["answered_questions"] = answered_questions_res.count or 0
        
        return stats
    except Exception as e:
        logger.exception("Supabase get_bot_statistics error: %s", e)
        return {}


def get_top_students_by_submissions(limit: int = 5) -> List[Dict[str, Any]]:
    """Get top students by submission count"""
    client = get_supabase()
    try:
        # Get all verified users with their submission counts
        users_res = client.table("verified_users").select("*").eq("status", "verified").execute()
        users = _get_response_data(users_res) or []
        
        top_students = []
        for user in users:
            telegram_id = user.get("telegram_id")
            if not telegram_id:
                continue
            
            # Count submissions
            submissions_res = client.table("assignments").select("id", count="exact").eq("telegram_id", telegram_id).execute()
            submission_count = submissions_res.count or 0
            
            if submission_count > 0:
                top_students.append({
                    "name": user.get("name", "Unknown"),
                    "username": user.get("username", "unknown"),
                    "telegram_id": telegram_id,
                    "submissions": submission_count,
                    "email": user.get("email", "N/A")
                })
        
        # Sort by submission count and return top N
        top_students.sort(key=lambda x: x["submissions"], reverse=True)
        return top_students[:limit]
    except Exception as e:
        logger.exception("Supabase get_top_students_by_submissions error: %s", e)
        return []










def update_assignment_grade(submission_id: int, grade: int, comment: Optional[str] = None) -> bool:
    client = get_supabase()
    try:
        update_data = {
            "grade": grade,
            "status": "graded",
            "graded_at": datetime.now(timezone.utc).isoformat()
        }
        if comment:
            update_data["comment"] = comment

        res = client.table("assignments").update(update_data).eq("id", submission_id).execute()
        data = _get_response_data(res)
        return bool(data)
    except Exception as e:
        logger.exception("Supabase update_assignment_grade error: %s", e)
        return False


def update_question_answer(question_id: int, answer: str) -> bool:
    client = get_supabase()
    try:
        update_data = {
            "answer": answer,
            "status": "answered",
            "answered_at": datetime.now(timezone.utc).isoformat()
        }
        res = client.table("questions").update(update_data).eq("id", question_id).execute()
        data = _get_response_data(res)
        return bool(data)
    except Exception as e:
        logger.exception("Supabase update_question_answer error: %s", e)
        return False


def get_faqs() -> List[Dict[str, Any]]:
    client = get_supabase()
    try:
        res = client.table("faqs").select("*").execute()
        data = _get_response_data(res)
        return data or []
    except Exception as e:
        logger.exception("Supabase get_faqs error: %s", e)
        return []


def get_tip_for_day(day_of_week: int) -> Optional[Dict[str, Any]]:
    client = get_supabase()
    try:
        res = client.table("tips").select("*").eq("day_of_week", day_of_week).limit(1).execute()
        data = _get_response_data(res)
        return data[0] if data else None
    except Exception as e:
        logger.exception("Supabase get_tip_for_day error: %s", e)
        return None


def add_manual_tip(content: str, day_of_week: int) -> Dict[str, Any]:
    client = get_supabase()
    try:
        payload = {
            "content": content,
            "day_of_week": day_of_week,
            "tip_type": "manual",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        res = client.table("tips").insert(payload).execute()
        data = _get_response_data(res)
        return data[0] if data else None
    except Exception as e:
        logger.exception("Supabase add_manual_tip error: %s", e)
        raise







    client = get_supabase()

    try:

        payload = {

            "telegram_id": telegram_id,

            "username": username,

            "module": module,

            "file_id": file_id,

            "file_name": file_name,

            "submission_type": submission_type,

            "status": "submitted",

            "submitted_at": datetime.now(timezone.utc).isoformat()

        }

        res = client.table("assignments").insert(payload).execute()
        data = _get_response_data(res)
        return data[0] if data else None

    except Exception as e:

        logger.exception("Supabase add_assignment_submission error: %s", e)

        raise







    client = get_supabase()

    try:

        res = client.table("assignments").select("*").eq("telegram_id", telegram_id)
        data = _get_response_data(res)
        return data or []

    except Exception as e:

        logger.exception("Supabase get_student_assignments error: %s", e)

        return []







    client = get_supabase()

    try:

        update_data = {

            "grade": grade,

            "status": "graded",

            "graded_at": datetime.now(timezone.utc).isoformat()

        }

        if comment:

            update_data["comment"] = comment

        

        res = client.table("assignments").update(update_data).eq("id", submission_id).execute()
        data = _get_response_data(res)
        return bool(data)

    except Exception as e:

        logger.exception("Supabase update_assignment_grade error: %s", e)

        return False







    client = get_supabase()

    try:

        payload = {

            "telegram_id": telegram_id,

            "username": username,

            "file_id": file_id,

            "file_name": file_name,

            "win_type": win_type,

            "shared_at": datetime.now(timezone.utc).isoformat()

        }

        res = client.table("wins").insert(payload).execute()
        data = _get_response_data(res)
        return data[0] if data else None

    except Exception as e:

        logger.exception("Supabase add_win error: %s", e)

        raise







    client = get_supabase()

    try:

        res = client.table("wins").select("*").eq("telegram_id", telegram_id).execute()
        data = _get_response_data(res)
        return data or []

    except Exception as e:

        logger.exception("Supabase get_student_wins error: %s", e)

        return []







    client = get_supabase()

    try:

        res = client.table("questions").select("*").eq("telegram_id", telegram_id).execute()
        data = _get_response_data(res)
        return data or []

    except Exception as e:

        logger.exception("Supabase get_student_questions error: %s", e)

        return []







    client = get_supabase()

    try:

        update_data = {

            "answer": answer,

            "status": "answered",

            "answered_at": datetime.now(timezone.utc).isoformat()

        }

        res = client.table("questions").update(update_data).eq("id", question_id).execute()
        data = _get_response_data(res)
        return bool(data)

    except Exception as e:

        logger.exception("Supabase update_question_answer error: %s", e)

        return False







    client = get_supabase()

    try:

        res = client.table("faqs").select("*").execute()
        data = _get_response_data(res)
        return data or []

    except Exception as e:

        logger.exception("Supabase get_faqs error: %s", e)

        return []







    client = get_supabase()

    try:

        payload = {

            "question": question,

            "answer": answer,

            "created_at": datetime.now(timezone.utc).isoformat()

        }

        res = client.table("faqs").insert(payload).execute()
        data = _get_response_data(res)
        return data[0] if data else None

    except Exception as e:

        logger.exception("Supabase add_faq error: %s", e)

        raise







    client = get_supabase()

    try:

        res = client.table("tips").select("*").eq("day_of_week", day_of_week).limit(1).execute()
        data = _get_response_data(res)
        return data[0] if data else None

    except Exception as e:

        logger.exception("Supabase get_tip_for_day error: %s", e)

        return None







    client = get_supabase()

    try:

        payload = {

            "content": content,

            "day_of_week": day_of_week,

            "tip_type": "manual",

            "created_at": datetime.now(timezone.utc).isoformat()

        }

        res = client.table("tips").insert(payload).execute()
        data = _get_response_data(res)
        return data[0] if data else None

    except Exception as e:

        logger.exception("Supabase add_manual_tip error: %s", e)

        raise







    client = get_supabase()

    

    # Get all verified users

    users_res = client.table("verified_users").select("*").eq("status", "verified")
    try:

        users = _get_response_data(users_res) or []

    except Exception as e:

        logger.exception("Supabase get_top_students error: %s", e)

        return []

    

    top_students = []

    for user in users:

        telegram_id = user.get("telegram_id")

        if not telegram_id:

            continue

        

        # Count assignments

        assignments_res = client.table("assignments").select("id", count="exact").eq("telegram_id", telegram_id).execute()
        assignment_count = assignments_res.count or 0

        

        # Count wins

        wins_res = client.table("wins").select("id", count="exact").eq("telegram_id", telegram_id).execute()
        wins_count = wins_res.count or 0

        

        if assignment_count >= 3 and wins_count >= 3:

            top_students.append({

                "telegram_id": telegram_id,

                "username": user.get("username", "unknown"),

                "name": user.get("name", "Unknown"),

                "assignments": assignment_count,

                "wins": wins_count,

                "joined_at": user.get("created_at", "Unknown")

            })

    

    return top_students







    client = get_supabase()

    try:

        res = client.table("verified_users").select("telegram_id").eq("status", "verified").execute()
        data = _get_response_data(res)
        return [user["telegram_id"] for user in (data or []) if user.get("telegram_id")]

    except Exception as e:

        logger.exception("Supabase get_all_verified_telegram_ids error: %s", e)

        return []







    client = get_supabase()

    try:

        res = client.table("verified_users").update({"badge": badge}).eq("telegram_id", telegram_id).execute()
        data = _get_response_data(res)
        return bool(data)

    except Exception as e:

        logger.exception("Supabase update_user_badge error: %s", e)

        return False






    """Get assignment by ID"""

    client = get_supabase()

    try:

        res = client.table("assignments").select("*").eq("id", assignment_id).execute()
        data = _get_response_data(res)
        return data[0] if data else None

    except Exception as e:

        logger.exception("Supabase get_assignment_by_id error: %s", e)

        return None

        data = _get_response_data(res)
        if data and len(data) > 0:
            return data[0] if data else None

        return None

    except Exception as e:

        logger.exception("Supabase check_verified_user error: %s", e)

        return None







    client = get_supabase()

    try:

        payload = {

            "telegram_id": telegram_id,

            "username": username,

            "module": module,

            "file_id": file_id,

            "file_name": file_name,

            "submission_type": submission_type,

            "status": "submitted",

            "submitted_at": datetime.now(timezone.utc).isoformat()

        }

        res = client.table("assignments").insert(payload).execute()
        data = _get_response_data(res)
        return data[0] if data else None

    except Exception as e:

        logger.exception("Supabase add_assignment_submission error: %s", e)

        raise







    client = get_supabase()

    try:

        res = client.table("assignments").select("*").eq("telegram_id", telegram_id)
        data = _get_response_data(res)
        return data or []

    except Exception as e:

        logger.exception("Supabase get_student_assignments error: %s", e)

        return []







    client = get_supabase()

    try:

        update_data = {

            "grade": grade,

            "status": "graded",

            "graded_at": datetime.now(timezone.utc).isoformat()

        }

        if comment:

            update_data["comment"] = comment

        

        res = client.table("assignments").update(update_data).eq("id", submission_id).execute()
        data = _get_response_data(res)
        return bool(data)

    except Exception as e:

        logger.exception("Supabase update_assignment_grade error: %s", e)

        return False







    client = get_supabase()

    try:

        payload = {

            "telegram_id": telegram_id,

            "username": username,

            "file_id": file_id,

            "file_name": file_name,

            "win_type": win_type,

            "shared_at": datetime.now(timezone.utc).isoformat()

        }

        res = client.table("wins").insert(payload).execute()
        data = _get_response_data(res)
        return data[0] if data else None

    except Exception as e:

        logger.exception("Supabase add_win error: %s", e)

        raise







    client = get_supabase()

    try:

        res = client.table("wins").select("*").eq("telegram_id", telegram_id).execute()
        data = _get_response_data(res)
        return data or []

    except Exception as e:

        logger.exception("Supabase get_student_wins error: %s", e)

        return []









        res = client.table("questions").update(update_data).eq("id", question_id).execute()
        data = _get_response_data(res)
        return bool(data)

    except Exception as e:

        logger.exception("Supabase update_question_answer error: %s", e)

        return False







    client = get_supabase()

    try:

        res = client.table("faqs").select("*").execute()
        data = _get_response_data(res)
        return data or []

    except Exception as e:

        logger.exception("Supabase get_faqs error: %s", e)

        return []







    client = get_supabase()

    try:

        payload = {

            "question": question,

            "answer": answer,

            "created_at": datetime.now(timezone.utc).isoformat()

        }

        res = client.table("faqs").insert(payload).execute()
        data = _get_response_data(res)
        return data[0] if data else None

    except Exception as e:

        logger.exception("Supabase add_faq error: %s", e)

        raise







    client = get_supabase()

    try:

        res = client.table("tips").select("*").eq("day_of_week", day_of_week).limit(1).execute()
        data = _get_response_data(res)
        return data[0] if data else None

    except Exception as e:

        logger.exception("Supabase get_tip_for_day error: %s", e)

        return None







    client = get_supabase()

    try:

        payload = {

            "content": content,

            "day_of_week": day_of_week,

            "tip_type": "manual",

            "created_at": datetime.now(timezone.utc).isoformat()

        }

        res = client.table("tips").insert(payload).execute()
        data = _get_response_data(res)
        return data[0] if data else None

    except Exception as e:

        logger.exception("Supabase add_manual_tip error: %s", e)

        raise







    client = get_supabase()

    

    # Get all verified users

    users_res = client.table("verified_users").select("*").eq("status", "verified")
    try:

        users = _get_response_data(users_res) or []

    except Exception as e:

        logger.exception("Supabase get_top_students error: %s", e)

        return []

    

    top_students = []

    for user in users:

        telegram_id = user.get("telegram_id")

        if not telegram_id:

            continue

        

        # Count assignments

        assignments_res = client.table("assignments").select("id", count="exact").eq("telegram_id", telegram_id).execute()
        assignment_count = assignments_res.count or 0

        

        # Count wins

        wins_res = client.table("wins").select("id", count="exact").eq("telegram_id", telegram_id).execute()
        wins_count = wins_res.count or 0

        

        if assignment_count >= 3 and wins_count >= 3:

            top_students.append({

                "telegram_id": telegram_id,

                "username": user.get("username", "unknown"),

                "name": user.get("name", "Unknown"),

                "assignments": assignment_count,

                "wins": wins_count,

                "joined_at": user.get("created_at", "Unknown")

            })

    

    return top_students







    client = get_supabase()

    try:

        res = client.table("verified_users").select("telegram_id").eq("status", "verified").execute()
        data = _get_response_data(res)
        return [user["telegram_id"] for user in (data or []) if user.get("telegram_id")]

    except Exception as e:

        logger.exception("Supabase get_all_verified_telegram_ids error: %s", e)

        return []







    client = get_supabase()

    try:

        res = client.table("verified_users").update({"badge": badge}).eq("telegram_id", telegram_id).execute()
        data = _get_response_data(res)
        return bool(data)

    except Exception as e:

        logger.exception("Supabase update_user_badge error: %s", e)

        return False






    """Get assignment by ID"""

    client = get_supabase()

    try:

        res = client.table("assignments").select("*").eq("id", assignment_id).execute()
        data = _get_response_data(res)
        return data[0] if data else None

    except Exception as e:

        logger.exception("Supabase get_assignment_by_id error: %s", e)

        return None
