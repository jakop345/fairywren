import eventlet
import eventlet.db_pool
import base64
import hashlib
import os
from psycopg2 import IntegrityError



class Auth(object):
	def __init__(self,salt):
		self.salt = salt
		
	def setConnectionPool(self,pool):
		self.connPool = pool

	def isUserMemberOfRole(self,userId,roles):
		with self.connPool.item() as conn:
			cur = conn.cursor()
			
			cur.execute("SELECT roles.name from rolemember left join roles on roles.id=rolemember.roleid where userid=%s;",(userId,));

			for role, in iter(cur.fetchone,None):
				if role in roles:
					return True
					
			return False
	def changePassword(self,userId,pwHash):
		saltedPw = self._saltPwhash(pwHash)
		with self.connPool.item() as conn:
			cur = conn.cursor()
			try: 
				cur.execute("UPDATE users SET password=%s where id=%s;",
				(saltedPw,userId,))
			except StandardError:
				return None
			conn.commit()
			cur.close()
				
		return True

	def _saltPwhash(self,pwHash):
		storedHash = hashlib.sha512()
		storedHash.update(self.salt)
		storedHash.update(pwHash)
		return base64.urlsafe_b64encode(storedHash.digest()).replace('=','')

	def addUser(self,username,pwHash):
		secretKey = hashlib.sha512()
		
		randomValue = os.urandom(1024)
		secretKey.update(randomValue)
		
		saltedPw = self._saltPwhash(pwHash)

		with self.connPool.item() as conn:
			cur = conn.cursor()
			
			try:
				cur.execute("INSERT into users (name,password,secretKey) VALUES(%s,%s,%s) returning users.id;",
					(username,
					saltedPw,
					base64.urlsafe_b64encode(secretKey.digest()).replace('=',''),) ) 
			except IntegrityError:
				return None
			conn.commit()
			
			newId, = cur.fetchone()
			cur.close()
			conn.close()
			
			return 'api/users/%x'  % newId
			
		
	def authenticateSecretKey(self,key):
		with self.connPool.item() as conn:
			cur = conn.cursor()
		
			cur.execute("Select 1 from users where secretKey=%s and password is not null;",
			(base64.urlsafe_b64encode(key).replace('=','') ,))
		
			allowed = cur.fetchone() != None
			cur.close()
			
			return allowed
		
	def authorizeInfoHash(self,info_hash):
		with self.connPool.item() as conn:
			cur = conn.cursor()
			cur.execute("Select 1 from torrents where infoHash=%(infoHash)s",
			{'infoHash' : base64.urlsafe_b64encode(info_hash).replace('=','') })
			
			allowed = cur.fetchone() != None
			cur.close()
		
			return allowed

	def authenticateUser(self,username,password):
		passwordHash = hashlib.sha512()
		passwordHash.update(self.salt)
		passwordHash.update(password)
		
		passwordHash = base64.urlsafe_b64encode(passwordHash.digest()).replace('=','')
		with self.connPool.item() as conn:
			cur = conn.cursor()
			cur.execute("Select id from users where name=%s and password=%s ;",
			(username,passwordHash))
			
			allowed = cur.fetchone() 
			cur.close()
			
			if allowed == None:
				return None
			userId, = allowed
			return userId;
			
			
			
			
		
