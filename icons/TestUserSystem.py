
from user_system import UserSystem

# 数据库配置，请根据你的数据库信息进行修改
db_host = 'localhost'
db_user = 'your_username'
db_password = 'your_password'

# 创建 UserSystem 实例
user_system = UserSystem(db_host, db_user, db_password)

# 测试添加用户
user_system.add_user('fqq', '139849lK58', 'fqq@example.com')

# 测试获取用户
user = user_system.get_user('fqq')
print(f'User found: {user}')

# 测试密码验证
correct_password = user_system.check_password('139849lK58', user[2])
print(f'Password correct: {correct_password}')
