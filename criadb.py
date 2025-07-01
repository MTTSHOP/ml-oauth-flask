import sqlite3

conn = sqlite3.connect('tokens.db')
c = conn.cursor()

c.execute('''
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    access_token TEXT,
    refresh_token TEXT,
    token_type TEXT,
    expires_in INTEGER,
    scope TEXT,
    user_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

conn.commit()
conn.close()

print("Banco de dados inicializado com sucesso!")