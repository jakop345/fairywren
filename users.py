import eventlet
import fairywren
import hashlib
import psycopg2
import logging
import os
import base64

class UserAlreadyExists(BaseException):
	pass

class Users(object):

	def __init__(self,salt):
		self.salt = salt
		self.connPool = None
		self.log = logging.getLogger('fairywren.users')
		self.log.info('Created')
		
	def createRoles(self,roles):
		numCreated = 0
		with self.connPool.item() as conn:
			for role in roles:
				cur = conn.cursor()
				
				try:
					cur.execute("Select id  from roles where name=%s;",(role,))
				except psycopg2.DatabaseError as e:
					cur.close()
					conn.rollback()
					self.log.exception('Failed checking for role %s',role, exc_info=True)
					raise e
				
				result = cur.fetchone()
				
				if result == None:
					try:
						cur.execute("Insert into roles (name)  VALUES(%s);",(role,))
					except psycopg2.DatabaseError as e:
						cur.close()
						conn.rollback()
						self.log.exception('Failed creating role %s',role, exc_info=True)
						raise e					
					
					self.log.info("Created role %s",role)
					numCreated += 1
				
			cur.close()		
			conn.commit()
		return numCreated
		
	def setUserRoles(self,roles,uid):

		roles = set(roles)
		with self.connPool.item() as conn:
			cur = conn.cursor()
			try:
				cur.execute("Select roles.name from rolemember left join roles on rolemember.roleid = roles.id where rolemember.userid =  %s",(uid,))
			except psycopg2.DatabaseError as e:
				cur.close()
				conn.rollback()
				self.log.exception('Failed getting roles for user:%.x',uid)
				raise e
				
			existingRoles = set()
			
			for row in cur:
				role, = row
				
				existingRoles.add(role)
			
			addRoles = roles.difference(existingRoles)
			removeRoles = existingRoles.difference(roles)
			
			for role in addRoles:
				try:
					cur.execute("Select id from roles where name = %s",(role,));
				except psycopg2.DatabaseError as e:
					cur.close()
					conn.rollback()
					self.log.exception('Failed selecting role %s',role,exc_info=True)
					raise e		
				
				result = cur.fetchone()
				if result == None:
					raise ValueError('Role %s does not exist' % role)
				roleid, = result				
				
				try:
					cur.execute("Insert into rolemember(roleid,userid) VALUES(%s,%s)  returning userid;",(roleid,uid))
				except psycopg2.IntegrityError as e:
					cur.close()
					conn.rollback()
					#The string '23503' is specified in the postgre documentation appendix
					#'PostgreSQL Error Codes'. It indicates foreign_key_violation.
					#This means the user does not exist.
					if e.pgcode == '23503':
						self.log.exception('Failed add uid:%x to role %s. User does not exist',uid,role,exc_info=True)
						raise ValueError('User with uid:%x does not exist' % uid)
					else:
						self.log.exception('Failed adding uid:%x to role %s',uid,role,exc_info=True)
						raise e
						
			for role in removeRoles:
				try:
					cur.execute("Select id from roles where name = %s",(role,));
				except psycopg2.DatabaseError as e:
					cur.close()
					conn.rollback()
					self.log.exception('Failed selecting role %s',role,exc_info=True)
					raise e		
				
				result = cur.fetchone()
				if result == None:
					raise ValueError('Role %s does not exist' % role)
				roleid, = result
					
				try:
					cur.execute("Delete from rolemember where userid = %s and roleid = %s ;",(uid,roleid));
				except psycopg2.DatabaseError as e:
					cur.close()
					conn.rollback()
					self.log.exception('Failed removing uid:%x from role %s',uid,role,exc_info=True)
					raise e		
					
			cur.close()
			conn.commit()
			
		return len(addRoles),len(removeRoles)
		
	def getUserRoles(self,uid):
		with self.connPool.item() as conn:
			cur = conn.cursor()
			
			try:
				cur.execute('Select roles.name from rolemember left join roles on roles.id = rolemember.roleid where userid = %s',(uid,));
			except psycopg2.DatabaseError as e:
				cur.close()
				conn.rollback()
				self.log.exception('Failed getting roles for user:%.x',uid)
				raise e
				
			roles = []
			for result in cur:
				role, = result
				roles.append(role)
				
			cur.close()
			
			conn.rollback()
		return roles
		
	def addUserToRole(self,role,uid):
		with self.connPool.item() as conn:
			cur = conn.cursor()
			
			try:
				cur.execute("Insert into rolemember (roleid,userid) select roles.id, %s from roles where name = %s returning userid;",(uid,role))
			except psycopg2.IntegrityError as e:
				cur.close()
				conn.rollback()
				#The string '23505' is specified in the postgre documentation appendix
				# 'PostgreSQL Error Codes' as 'unique_violation' and corresponds
				#to primary key violations. If this occurs it just means
				#the user is already a member of the role. So it can safely be ignored.
				#The string '23503' indicates foreign_key_violation. This means the user
				# does not exist and should not be ignored
				if e.pgcode == '23505':
					return
				elif e.pgcode == '23503':
					self.log.exception('Failed add uid:%x to role %s. User does not exist',uid,role,exc_info=True)
					raise ValueError('User with uid:%x does not exist' % uid)
				else:
					self.log.exception('Failed adding uid:%x to role %s',uid,role,exc_info=True)
					raise e
			except psycopg2.DatabaseError as e:
				cur.close()
				conn.rollback()
				self.log.exception('Failed adding uid:%x to role %s',uid,role,exc_info=True)
				raise e			
				
			result = cur.fetchone()
			cur.close()
			conn.commit()
			if result == None:
				raise ValueError('Role %s does not exist' % role);

			
	def removeUserFromRole(self,role,uid):
		with self.connPool.item() as conn:
			cur = conn.cursor()
			
			try:
				cur.execute("Select id from roles where name = %s",(role,));
			except psycopg2.DatabaseError as e:
				cur.close()
				conn.rollback()
				self.log.exception('Failed selecting role %s',role,exc_info=True)
				raise e		
			
			result = cur.fetchone()
			if result == None:
				raise ValueError('Role %s does not exist' % role)
			roleid, = result
				
			
			try:
				cur.execute("Delete from rolemember where userid = %s and roleid = %s ;",(uid,roleid));
			except psycopg2.DatabaseError as e:
				cur.close()
				conn.rollback()
				self.log.exception('Failed removing uid:%x from role %s',uid,role,exc_info=True)
				raise e		
				
			cur.close()
			conn.commit()
			
		
	def setConnectionPool(self,pool):
		self.connPool = pool

	def _saltPwhash(self,pwHash):
		
		if len(pwHash) != 64:
			raise ValueError('password hash should be 64 bytes')
		
		storedHash = hashlib.sha512()
		storedHash.update(self.salt)
		storedHash.update(pwHash)
		return base64.urlsafe_b64encode(storedHash.digest()).replace('=','')
		
	def _genSecretKey(self):
		secretKey = hashlib.sha512()
		randomValue = os.urandom(1024)
		secretKey.update(randomValue)
		return base64.urlsafe_b64encode(secretKey.digest()).replace('=','')
	
	def addUser(self,username,pwHash):
		'''
		username - string, username of new user
		pwHash - string, 64 byte password
		'''
		self.log.debug('Trying to add user %s',username)
		secretKey = self._genSecretKey()
		
		saltedPw = self._saltPwhash(pwHash)

		with self.connPool.item() as conn:
			cur = conn.cursor()
			
			try:
				cur.execute("INSERT into users (name,password,secretKey) VALUES(%s,%s,%s) returning users.id;",
					(username,
					saltedPw,
					secretKey,) ) 
			except psycopg2.IntegrityError as e:
				cur.close()
				conn.rollback()
				#This string is specified in the postgre documentation appendix
				# 'PostgreSQL Error Codes' as 'unique_violation' and corresponds
				#to primary key violations
				if e.pgcode == '23505':
					raise UserAlreadyExists('User with that username already exists')
				self.log.exception('Failed adding new user',exc_info=True)
				raise e
			except psycopg2.DatabaseError as e:
				cur.close()
				conn.rollback()
				self.log.exception('Failed adding new user',exc_info=True)
				raise e
				
			conn.commit()
			
			newId, = cur.fetchone()
			cur.close()

			self.log.debug('Added user, new id %.8x', newId)
			return 'api/users/%.8x'  % newId,newId
			
	
	def claimInvite(self,inviteSecret,username,pwHash):
		'''
		inviteSecret - string, 32 bytes
		username - string, username of new user
		pwHash - string, 64 byte password
		'''
		self.log.debug('Trying to claim invite and create user %s',username)
		secretKey = self._genSecretKey()
		saltedPw = self._saltPwhash(pwHash)
		inviteSecret = base64.urlsafe_b64encode(inviteSecret).replace('=','')
		
		with self.connPool.item() as conn:
			cur = conn.cursor()
			
			try:
				cur.execute('INSERT into users (name,password,secretkey) VALUES(%s,%s,%s) returning users.id;',
				(username,saltedPw,secretKey,))
				uid, = cur.fetchone()
			except psycopg2.IntegrityError as e:
				cur.close()
				conn.rollback()
				#This string is specified in the postgre documentation appendix
				# 'PostgreSQL Error Codes' as 'unique_violation' and corresponds
				#to primary key violations
				if e.pgcode == '23505':
					raise UserAlreadyExists('User with that username already exists')
				self.log.exception('Failed adding new user',exc_info=True)
				raise e
			except psycopg2.DatabaseError as e:
				cur.close()
				conn.rollback()
				self.log.exception('Failed adding new user',exc_info=True)
				raise e		
			
			try:
				cur.execute("UPDATE INVITES set invitee = %s , accepted = timezone('UTC',CURRENT_TIMESTAMP) where secret = %s and invitee is null returning 1;",
				(uid,
				inviteSecret,))
				success = cur.fetchone()
			except psycopg2.DatabaseError as e:
				cur.close()
				conn.rollback()
				self.log.exception('Failed accepting invite',exc_info = True)
				raise e
			
			cur.close()
			
			if success==None:
				conn.rollback()
				raise ValueError('Invite does not exist or has already been claimed')
			conn.commit()
		self.log.info('Claimed invite for user %s (%.8x)',username,uid)
		return  fairywren.USER_FMT % uid 
				
	def listInvitesByUser(self,userId):
		with self.connPool.item() as conn:
			cur = conn.cursor()
			
			try:
				cur.execute('Select creationdate,secret FROM invites WHERE inviter = %s and invitee is null order by creationdate desc;',(userId,))
			except psycopg2.DatabaseError as e:
				self.log.exception('Failed listing invites for user %.8x',userId,exc_info=True)
				raise e
				
			for row in cur:
				created,secret = row
				secret = base64.urlsafe_b64decode(secret + '=')
				yield {'created' : created, 'href' : fairywren.INVITE_FMT % secret}
				
			cur.close()
			conn.rollback()
				
			
	def getInviteState(self,inviteSecret):
		'''
		inviteSecret -- string, 32 bytes identifying the invite
		
		Returns True if claimed, False if not
		'''
		inviteSecret = base64.urlsafe_b64encode(inviteSecret).replace('=','')
		with self.connPool.item() as conn:
			cur = conn.cursor()
			
			try: 
				cur.execute("Select invitee from invites WHERE secret = %s;", (inviteSecret,))
				row = cur.fetchone()
			except psycopg2.DatabaseError as e:
				self.log.exception('Failed creating invite',exc_info=True)
				raise e
			finally:
				cur.close()
				conn.rollback()
				
			if row == None:
				raise ValueError('No invite exists with that secret')
				
		invitee, = row
		
		return None != invitee 
		
	def createInvite(self,creatorId):
		h = hashlib.md5()
		h.update(os.urandom(1024))
		h.update(str(creatorId))
		h.update(self.salt)
		
		secret = h.digest()
		h.update(h.digest())
		h.update(os.urandom(1024))
		secret += h.digest()
		
		with self.connPool.item() as conn:
			cur = conn.cursor()
			
			try:
				cur.execute("INSERT into invites (secret,inviter,creationdate) VALUES(%s,%s,timezone('UTC',CURRENT_TIMESTAMP));" , (base64.urlsafe_b64encode(secret).replace('=',''),creatorId,))
			except psycopg2.IntegrityError as e:
				conn.rollback()
				# 'foreign_key_violation' - violation of 'inviter' foreign key
				# i.e. user with uid doesn't exist
				if e.pgcode == '23503':
					raise ValueError('User does not exist with that uid')
				self.log.exception('Failed creating invite',exc_info=True)
				raise e
			except psycopg2.DatabaseError as e:
				conn.rollback()
				self.log.exception('Failed creating invite',exc_info=True)
				raise e
			conn.commit()
			cur.close()
		self.log.info('Created invite for user %.8x',creatorId)
		return fairywren.INVITE_FMT % secret
		
	def getInfo(self,idNumber):
		with self.connPool.item() as conn:
			cur = conn.cursor()
			try:
				cur.execute("Select users.name,count(torrents.creator) from users left join torrents on (torrents.creator=users.id) where users.id=%s group by users.name;",(idNumber,))
				result = cur.fetchone()
			except psycopg2.DatabaseError as e:
				self.log.exception('Failed getting info for user',exc_info=True)
				raise e
			finally:
				cur.close()
				conn.rollback()
				
			retval = {}
			if result == None:			
				return None
			else:
				name,numberOfTorrents = result
				retval =  {'numberOfTorrents' : numberOfTorrents, 
				'name':name, 
				'password' : {'href' : fairywren.USER_PASSWORD_FMT % idNumber },
				'invites' : {'href' : fairywren.USER_INVITES_FMT % idNumber } }
			
			return retval
			


