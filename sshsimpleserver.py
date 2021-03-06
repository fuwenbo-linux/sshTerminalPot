# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.
import subprocess
from twisted.cred import portal
from twisted.cred.checkers import InMemoryUsernamePasswordDatabaseDontUse
from twisted.conch import avatar
from twisted.conch.checkers import SSHPublicKeyChecker, InMemorySSHKeyDB
from twisted.conch.ssh import factory, userauth, connection, keys, session
from twisted.conch.ssh.transport import SSHServerTransport
from twisted.internet import reactor, protocol
#from twisted.python import log
from twisted.python import components
from zope.interface import implementer
from twisted.internet.threads import deferToThread
import sys
#log.startLogging(sys.stderr)

# Path to RSA SSH keys used by the server.
SERVER_RSA_PRIVATE = 'ssh-keys/ssh_host_rsa_key'
SERVER_RSA_PUBLIC = 'ssh-keys/ssh_host_rsa_key.pub'

# Path to RSA SSH keys accepted by the server.
CLIENT_RSA_PUBLIC = 'ssh-keys/client_rsa.pub'
PRIMES = {
    2048: [(2, 24265446577633846575813468889658944748236936003103970778683933705240497295505367703330163384138799145013634794444597785054574812547990300691956176233759905976222978197624337271745471021764463536913188381724789737057413943758936963945487690939921001501857793275011598975080236860899147312097967655185795176036941141834185923290769258512343298744828216530595090471970401506268976911907264143910697166165795972459622410274890288999065530463691697692913935201628660686422182978481412651196163930383232742547281180277809475129220288755541335335798837173315854931040199943445285443708240639743407396610839820418936574217939)],
    4096: [(2, 889633836007296066695655481732069270550615298858522362356462966213994239650370532015908457586090329628589149803446849742862797136176274424808060302038380613106889959709419621954145635974564549892775660764058259799708313210328185716628794220535928019146593583870799700485371067763221569331286080322409646297706526831155237865417316423347898948704639476720848300063714856669054591377356454148165856508207919637875509861384449885655015865507939009502778968273879766962650318328175030623861285062331536562421699321671967257712201155508206384317725827233614202768771922547552398179887571989441353862786163421248709273143039795776049771538894478454203924099450796009937772259125621285287516787494652132525370682385152735699722849980820612370907638783461523042813880757771177423192559299945620284730833939896871200164312605489165789501830061187517738930123242873304901483476323853308396428713114053429620808491032573674192385488925866607192870249619437027459456991431298313382204980988971292641217854130156830941801474940667736066881036980286520892090232096545650051755799297658390763820738295370567143697617670291263734710392873823956589171067167839738896249891955689437111486748587887718882564384870583135509339695096218451174112035938859)],
    }



class ExampleAvatar(avatar.ConchUser):
    """
    The avatar is used to configure SSH services/sessions/subsystems for
    an account.

    This account will use L{session.SSHSession} to handle a channel of
    type I{session}.
    """
    def __init__(self, username):
        avatar.ConchUser.__init__(self)
        self.username = username
        self.channelLookup.update({b'session':session.SSHSession})



@implementer(portal.IRealm)
class ExampleRealm(object):
    """
    When using Twisted Cred, the pluggable authentication framework, the
    C{requestAvatar} method should return a L{avatar.ConchUser} instance
    as required by the Conch SSH server.
    """
    def requestAvatar(self, avatarId, mind, *interfaces):
        """
        See: L{portal.IRealm.requestAvatar}
        """
        return interfaces[0], ExampleAvatar(avatarId), lambda: None



class EchoProtocol(protocol.Protocol):
    """
    This is our protocol that we will run over the shell session.
    """
    def __init__(self):
        self.data = b''
        self.proc = None
    def __deal_the_shell_command(self):
        #stimulate a ping command
        cmd = self.data.decode().split(" ")
        try:
            self.proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            for line in self.proc.stdout:
                line = line.decode()
                line = line.replace("\n","")
                self.transport.write(line.encode()+b"\r\n")
            for line in self.proc.stderr:
                line = line.decode()
                line = line.replace("\n", "")
                self.transport.write(b"\r\n"+line.encode() + b"\r\n")
        except FileNotFoundError:
            #deal unknown command
            data = self.data.decode()+" :"+" can't find terminal!"
            self.transport.write(b"\r\n"+data.encode()+b"\r\n")
        self.data = b''
    def normalizeData(self,data):
        if data == b'\x7f':
            #deal del
            self.data = self.data[0:-1]
        elif data ==b'\x03':
            #deal ctrl+c
            if self.proc !=None and self.proc.poll() ==None:
                self.proc.terminate()
                self.proc.kill()
            if len(self.data) > 0:
                data = '\t****^c\r\n'
            else:
                data = '^c\r\n'
            self.data = b""
        elif data == b"\r":
            #deal enter
            if len(self.data) >0:
                # deal when data len is big than 0
                self.__deal_the_shell_command()
        else:
            self.data+= data
        return data
    def normalizeCallback(self,data):
        if data ==b'\x7f':
            # self.transport.write(b"\b  \b\b")
            self.transport.write(b"\b \b")
            #just show the each command
            #print(self.data)
        else:
            self.transport.write(data)
    def dataReceived(self, data):
        deferToThread(self.normalizeData,data).addCallback(self.normalizeCallback)

class ExampleSession(object):
    def __init__(self, avatar):
        """
        In this example the avatar argument is not used for session selection,
        but for example you can use it to limit I{shell} or I{exec} access
        only to specific accounts.
        """
    def getPty(self, term, windowSize, attrs):
        """
        We don't support pseudo-terminal sessions.
        """


    def execCommand(self, proto, cmd):
        """
        We don't support command execution sessions.
        """
        raise Exception("not executing commands")

    def openShell(self, transport):
        """
        Use our protocol as shell session.
        """
        protocol = EchoProtocol()
        # Connect the new protocol to the transport and the transport
        # to the new protocol so they can communicate in both directions.
        protocol.makeConnection(transport)
        transport.makeConnection(session.wrapProtocol(protocol))

    def eofReceived(self):
        pass

    def closed(self):
        pass



components.registerAdapter(ExampleSession, ExampleAvatar, session.ISession)



class ExampleFactory(factory.SSHFactory):
    """
    This is the entry point of our SSH server implementation.

    The SSH transport layer is implemented by L{SSHTransport} and is the
    protocol of this factory.

    Here we configure the server's identity (host keys) and handlers for the
    SSH services:
    * L{connection.SSHConnection} handles requests for the channel multiplexing
      service.
    * L{userauth.SSHUserAuthServer} handlers requests for the user
      authentication service.
    """
    protocol = SSHServerTransport
    # Server's host keys.
    # To simplify the example this server is defined only with a host key of
    # type RSA.
    publicKeys = {
        b'ssh-rsa': keys.Key.fromFile(SERVER_RSA_PUBLIC)
    }
    privateKeys = {
        b'ssh-rsa': keys.Key.fromFile(SERVER_RSA_PRIVATE)
    }
    # Service handlers.
    services = {
        b'ssh-userauth': userauth.SSHUserAuthServer,
        b'ssh-connection': connection.SSHConnection
    }

    def getPrimes(self):
        """
        See: L{factory.SSHFactory}
        """
        return PRIMES


portal = portal.Portal(ExampleRealm())
passwdDB = InMemoryUsernamePasswordDatabaseDontUse()
passwdDB.addUser(b'admin', b'123')
sshDB = SSHPublicKeyChecker(InMemorySSHKeyDB(
    {b'user': [keys.Key.fromFile(CLIENT_RSA_PUBLIC)]}))
portal.registerChecker(passwdDB)
portal.registerChecker(sshDB)
ExampleFactory.portal = portal

if __name__ == '__main__':
    reactor.listenTCP(5022, ExampleFactory())
    reactor.run()