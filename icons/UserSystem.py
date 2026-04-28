
import pymysql
import bcrypt

class UserSystem:
    def __init__(self, host, user, password, db_name='user_system', table_name='users'):
        self.db_name = db_name
        self.table_name = table_name
        self.connection = pymysql.connect(host=host, user=user, password=password, database=db_name)
        self.cursor = self.connection.cursor()

        self.create_database()
        self.setup_tables()

    def create_database(self):
        self.cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self.db_name};")
        self.cursor.execute(f"USE {self.db_name};")

    def setup_tables(self):
        tables = {
            self.table_name: (
                'id INT AUTO_INCREMENT PRIMARY KEY, '
                'username VARCHAR(50) NOT NULL UNIQUE, '
                'password VARCHAR(255) NOT NULL, '
                'email VARCHAR(100) UNIQUE, '
                'created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP'
            )
        }
        for table_name, table_schema in tables.items():
            self.create_table(table_name, table_schema)

    def create_table(self, table_name, table_schema):
        self.cursor.execute(f'CREATE TABLE IF NOT EXISTS {table_name} ({table_schema});')
        self.connection.commit()

    def add_user(self, username, password, email):
        if not (8 <= len(password) <= 20):
            raise ValueError('Password must be between 8 and 20 characters long')
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        sql = f'INSERT INTO {self.table_name} (username, password, email) VALUES (%s, %s, %s);'
        self.cursor.execute(sql, (username, hashed_password, email))
        self.connection.commit()

    def get_user(self, username):
        sql = f'SELECT * FROM {self.table_name} WHERE username = %s;'
        self.cursor.execute(sql, (username,))
        return self.cursor.fetchone()

    def check_password(self, input_password, stored_password):
        return bcrypt.checkpw(input_password.encode('utf-8'), stored_password.encode('utf-8'))

    def __del__(self):
        self.connection.close()
