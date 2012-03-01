#!/bin/env python

import time
import sys
import httplib
import base64

from github import Github

### @todo From ReplayDataForIntegrationTest.*.txt files and ReferenceOfApis.md, build a coverage of the API by the integration test

class RecordReplayException( Exception ):
    pass

class RecordingHttpsConnection:
    class HttpResponse( object ):
        def __init__( self, file, res ):
            self.status = res.status
            self.__headers = res.getheaders()
            self.__output = res.read()
            file.write( str( self.status ) + "\n" )
            file.write( str( self.__headers ) + "\n" )
            file.write( str( self.__output ) + "\n" )

        def getheaders( self ):
            return self.__headers

        def read( self ):
            return self.__output

    __realHttpsConnection = httplib.HTTPSConnection

    def __init__( self, file, *args, **kwds ):
        self.__file = file
        self.__cnx = self.__realHttpsConnection( *args, **kwds )

    def request( self, verb, url, input, headers ):
        self.__cnx.request( verb, url, input, headers )
        del headers[ "Authorization" ] # Do not let sensitive info in git :-p
        self.__file.write( verb + " " + url + " " + str( headers ) + " " + input + "\n" )

    def getresponse( self ):
        return RecordingHttpsConnection.HttpResponse( self.__file, self.__cnx.getresponse() )

    def close( self ):
        self.__file.write( "\n" )
        return self.__cnx.close()

class ReplayingHttpsConnection:
    class HttpResponse( object ):
        def __init__( self, file ):
            self.status = int( file.readline().strip() )
            self.__headers = eval( file.readline().strip() )
            self.__output = file.readline().strip()

        def getheaders( self ):
            return self.__headers

        def read( self ):
            return self.__output

    def __init__( self, file ):
        self.__file = file

    def request( self, verb, url, input, headers ):
        del headers[ "Authorization" ]
        if( self.__file.readline().strip() != verb + " " + url + " " + str( headers ) + " " + input ):
            raise RecordReplayException( "This test has been changed since last record. Please re-run this script with argument '--record'" )

    def getresponse( self ):
        return ReplayingHttpsConnection.HttpResponse( self.__file )

    def close( self ):
        self.__file.readline()

class IntegrationTest:
    cobayeUser = "Lyloa"
    cobayeOrganization = "BeaverSoftware"

    def main( self, argv ):
        if len( argv ) >= 1:
            if argv[ 0 ] == "--record":
                print "Record mode: this script is really going to do requests to github.com"
                argv = argv[ 1: ]
                record = True
            elif argv[ 0 ] == "--list":
                print "List of available tests:"
                print "\n".join( self.listTests() )
                return
        else:
            print "Replay mode: this script will used requests to and replies from github.com recorded in previous runs in record mode"
            record = False

        if len( argv ) == 0:
            tests = self.listTests()
        else:
            tests = argv
        self.runTests( tests, record )

    def prepareRecord( self, test ):
        self.avoidError500FromGithub = lambda: time.sleep( 1 )
        try:
            import GithubCredentials
            self.g = Github( GithubCredentials.login, GithubCredentials.password )
            file = open( self.__fileName( test ), "w" )
            httplib.HTTPSConnection = lambda *args, **kwds: RecordingHttpsConnection( file, *args, **kwds )
        except ImportError:
            raise RecordReplayException( textwrap.dedent( """\
                Please create a 'GithubCredentials.py' file containing:"
                login = '<your github login>'"
                password = '<your github password>'""" ) )

    def prepareReplay( self, test ):
        self.avoidError500FromGithub = lambda: 0
        try:
            file = open( self.__fileName( test ) )
            httplib.HTTPSConnection = lambda *args, **kwds: ReplayingHttpsConnection( file )
            self.g = Github( "login", "password" )
        except IOError:
            raise RecordReplayException( "This test has never been recorded. Please re-run this script with argument '--record'" )

    def __fileName( self, test ):
        return "ReplayDataForIntegrationTest." + test + ".txt"

    def listTests( self ):
        return [ f[ 4: ] for f in dir( self ) if f.startswith( "test" ) ]

    def runTests( self, tests, record ):
        for test in tests:
            print
            print test
            try:
                if record:
                    self.prepareRecord( test )
                else:
                    self.prepareReplay( test )
                getattr( self, "test" + test )()
            except RecordReplayException, e:
                print "*" * len( str( e ) )
                print e
                print "*" * len( str( e ) )

    def testEditAuthenticatedUser( self ):
        print "Changing your user name (and reseting it)"
        u = self.g.get_user()
        originalName = u.name
        tmpName = u.name + " (edited by PyGithub)"
        print u.name, "->",
        u.edit( name = tmpName )
        print u.name, "->",
        u.edit( name = originalName )
        print u.name

    def testNamedUserDetails( self ):
        u = self.g.get_user( self.cobayeUser )
        print u.login, "(" + u.name + ") is from", u.location
        self.printList( "Repos", u.get_repos(), lambda r: r.name )

    def testOrganizationDetails( self ):
        o = self.g.get_organization( "github" )
        print o.login, "(" + o.name + ") is in", o.location
        self.printList( "Public members", o.get_public_members(), lambda m: m.login )
        self.printList( "Members", o.get_members(), lambda m: m.login )
        self.printList( "Repos", o.get_repos(), lambda r: r.name )

    def testEditOrganization( self ):
        o = self.g.get_organization( self.cobayeOrganization )
        r = o.create_repo( "TestPyGithub" )
        t = o.create_team( "PyGithubTesters", permission = "push" )
        self.printList( "Teams", o.get_teams(), lambda t: t.name )
        u = self.g.get_user( self.cobayeUser )
        print t.name, t.has_in_repos( r ), t.has_in_members( u )
        t.add_to_members( u )
        t.add_to_repos( r )
        print t.name, t.has_in_repos( r ), t.has_in_members( u )
        self.printList( "Team members", t.get_members(), lambda m: m.login )
        self.printList( "Team repos", t.get_repos(), lambda r: r.name )
        t.remove_from_members( u )
        t.remove_from_repos( r )
        print t.name, t.has_in_repos( r ), t.has_in_members( u )
        t.delete()
        self.printList( "Teams", o.get_teams(), lambda t: t.name )

    def printList( self, title, iterable, f = lambda x: x ):
        print title + ":", ", ".join( f( x ) for x in iterable[ :10 ] ), "..." if len( iterable ) > 10 else ""

IntegrationTest().main( sys.argv[ 1: ] )
