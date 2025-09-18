import sqlite3
conn = sqlite3.connect('C:/Users/ERI DANIEL/Desktop/avap_bot/student_data.db')
cursor = conn.cursor()
cursor.execute("SELECT code, telegram_id, username, question, chat_id, status FROM questions")
print(cursor.fetchall())
conn.close()