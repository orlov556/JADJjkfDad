import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

class Database:
    def __init__(self, database_url):
        self.database_url = database_url
        self.connect()
        self.create_tables()
    
    def connect(self):
        self.conn = psycopg2.connect(self.database_url)
        self.conn.autocommit = False
    
    def execute(self, query, params=None, fetch=False):
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params or [])
            if fetch:
                return cur.fetchall()
            self.conn.commit()
    
    def create_tables(self):
        self.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                name TEXT, login TEXT, avatar TEXT,
                stars INTEGER DEFAULT 0, spent INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active', role TEXT DEFAULT 'user',
                rating REAL DEFAULT 5.0, reviews INTEGER DEFAULT 0,
                bio TEXT, referrer BIGINT, referrals TEXT,
                registered TEXT
            )
        ''')
        
        self.execute('''
            CREATE TABLE IF NOT EXISTS items (
                id SERIAL PRIMARY KEY,
                title TEXT, price INTEGER, category TEXT,
                description TEXT, photo TEXT,
                seller TEXT, seller_avatar TEXT, time TEXT,
                views INTEGER DEFAULT 0, seller_id BIGINT,
                status TEXT, moderation TEXT, premium INTEGER DEFAULT 0,
                reject_reason TEXT
            )
        ''')
        
        self.execute('''
            CREATE TABLE IF NOT EXISTS favorites (
                id SERIAL PRIMARY KEY,
                user_id BIGINT, item_id INTEGER,
                UNIQUE(user_id, item_id)
            )
        ''')
        
        self.execute('''
            CREATE TABLE IF NOT EXISTS chats (
                id SERIAL PRIMARY KEY,
                user1_id BIGINT, user2_id BIGINT,
                messages TEXT, last_message TEXT, last_time TEXT,
                unread1 INTEGER DEFAULT 0, unread2 INTEGER DEFAULT 0
            )
        ''')
        
        self.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT, amount INTEGER,
                description TEXT, date TEXT, type TEXT
            )
        ''')
        
        print("✅ Tables created")
    
    def add_user(self, user_id, name, login, referrer=None):
        user = self.get_user(user_id)
        if not user:
            self.execute('''
                INSERT INTO users (user_id, name, login, referrer, registered)
                VALUES (%s, %s, %s, %s, %s)
            ''', (user_id, name, login, referrer, datetime.now().strftime("%Y-%m-%d")))
            if referrer:
                self.execute('UPDATE users SET stars = stars + 15 WHERE user_id = %s', (referrer,))
                self.add_transaction(referrer, 15, f"Реферал: {name}", "earn")
        return self.get_user(user_id)
    
    def get_user(self, user_id):
        result = self.execute('SELECT * FROM users WHERE user_id = %s', (user_id,), fetch=True)
        return result[0] if result else None
    
    def update_user(self, user_id, **kwargs):
        for key, value in kwargs.items():
            self.execute(f'UPDATE users SET {key} = %s WHERE user_id = %s', (value, user_id))
    
    def add_item(self, item):
        self.execute('''
            INSERT INTO items (title, price, category, description, photo,
                             seller, seller_avatar, time, seller_id, status, moderation, premium)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', item)
        result = self.execute('SELECT lastval()', fetch=True)
        return result[0]['lastval'] if result else None
    
    def get_items(self, status="approved"):
        return self.execute('SELECT * FROM items WHERE moderation = %s ORDER BY premium DESC, id DESC', (status,), fetch=True)
    
    def get_item(self, item_id):
        result = self.execute('SELECT * FROM items WHERE id = %s', (item_id,), fetch=True)
        return result[0] if result else None
    
    def update_item(self, item_id, **kwargs):
        for key, value in kwargs.items():
            self.execute(f'UPDATE items SET {key} = %s WHERE id = %s', (value, item_id))
    
    def delete_item(self, item_id):
        self.execute('DELETE FROM items WHERE id = %s', (item_id,))
    
    def add_favorite(self, user_id, item_id):
        self.execute('INSERT INTO favorites (user_id, item_id) VALUES (%s, %s) ON CONFLICT DO NOTHING', (user_id, item_id))
    
    def remove_favorite(self, user_id, item_id):
        self.execute('DELETE FROM favorites WHERE user_id = %s AND item_id = %s', (user_id, item_id))
    
    def get_favorites(self, user_id):
        result = self.execute('SELECT item_id FROM favorites WHERE user_id = %s', (user_id,), fetch=True)
        return [r['item_id'] for r in result]
    
    def add_transaction(self, user_id, amount, desc, type_="spend"):
        self.execute('''
            INSERT INTO transactions (user_id, amount, description, date, type)
            VALUES (%s, %s, %s, %s, %s)
        ''', (user_id, amount, desc, datetime.now().strftime("%Y-%m-%d"), type_))
    
    def get_transactions(self, user_id):
        return self.execute('SELECT * FROM transactions WHERE user_id = %s ORDER BY id DESC', (user_id,), fetch=True)
