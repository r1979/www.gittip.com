from __future__ import print_function, unicode_literals

import datetime
import random
from decimal import Decimal

import pytest
from aspen.utils import utcnow
from gittip import NotSane
from gittip.exceptions import (
    HasBigTips,
    UsernameIsEmpty,
    UsernameTooLong,
    UsernameAlreadyTaken,
    UsernameContainsInvalidCharacters,
    UsernameIsRestricted,
    NoSelfTipping,
    NoTippee,
    BadAmount,
)
from gittip.models.account_elsewhere import AccountElsewhere
from gittip.models.participant import (
    LastElsewhere, NeedConfirmation, NonexistingElsewhere, Participant, TeamCantBeOnlyAuth
)
from gittip.testing import Harness


# TODO: Test that accounts elsewhere are not considered claimed by default


class TestNeedConfirmation(Harness):
    def test_need_confirmation1(self):
        assert not NeedConfirmation(False, False, False)

    def test_need_confirmation2(self):
        assert NeedConfirmation(False, False, True)

    def test_need_confirmation3(self):
        assert not NeedConfirmation(False, True, False)

    def test_need_confirmation4(self):
        assert NeedConfirmation(False, True, True)

    def test_need_confirmation5(self):
        assert NeedConfirmation(True, False, False)

    def test_need_confirmation6(self):
        assert NeedConfirmation(True, False, True)

    def test_need_confirmation7(self):
        assert NeedConfirmation(True, True, False)

    def test_need_confirmation8(self):
        assert NeedConfirmation(True, True, True)


class TestAbsorptions(Harness):
    # TODO: These tests should probably be moved to absorptions tests
    def setUp(self):
        Harness.setUp(self)
        now = utcnow()
        hour_ago = now - datetime.timedelta(hours=1)
        for i, username in enumerate(['alice', 'bob', 'carl']):
            p = self.make_participant( username
                                     , claimed_time=hour_ago
                                     , last_bill_result=''
                                     , balance=Decimal(i)
                                      )
            setattr(self, username, p)

        deadbeef = self.make_participant('deadbeef', balance=Decimal('18.03'), elsewhere='twitter')
        self.expected_new_balance = self.bob.balance + deadbeef.balance
        deadbeef_twitter = AccountElsewhere.from_user_name('twitter', 'deadbeef')

        self.carl.set_tip_to(self.bob, '1.00')
        self.alice.set_tip_to(deadbeef, '1.00')
        self.bob.take_over(deadbeef_twitter, have_confirmation=True)
        self.deadbeef_archived = Participant.from_id(deadbeef.id)

    def test_participant_can_be_instantiated(self):
        expected = Participant
        actual = Participant.from_username('alice').__class__
        assert actual is expected

    def test_bob_has_two_dollars_in_tips(self):
        expected = Decimal('2.00')
        actual = self.bob.receiving
        assert actual == expected

    def test_alice_gives_to_bob_now(self):
        expected = Decimal('1.00')
        actual = self.alice.get_tip_to('bob')
        assert actual == expected

    def test_deadbeef_is_archived(self):
        actual = self.db.one( "SELECT count(*) FROM absorptions "
                              "WHERE absorbed_by='bob' AND absorbed_was='deadbeef'"
                             )
        expected = 1
        assert actual == expected

    def test_alice_doesnt_gives_to_deadbeef_anymore(self):
        expected = Decimal('0.00')
        actual = self.alice.get_tip_to('deadbeef')
        assert actual == expected

    def test_alice_doesnt_give_to_whatever_deadbeef_was_archived_as_either(self):
        expected = Decimal('0.00')
        actual = self.alice.get_tip_to(self.deadbeef_archived.username)
        assert actual == expected

    def test_there_is_no_more_deadbeef(self):
        actual = Participant.from_username('deadbeef')
        assert actual is None

    def test_balance_was_transferred(self):
        fresh_bob = Participant.from_username('bob')
        assert fresh_bob.balance == self.bob.balance == self.expected_new_balance
        assert self.deadbeef_archived.balance == 0


class TestTakeOver(Harness):

    def test_cross_tip_doesnt_become_self_tip(self):
        alice_twitter = self.make_elsewhere('twitter', 1, 'alice')
        bob_twitter   = self.make_elsewhere('twitter', 2, 'bob')
        alice = alice_twitter.opt_in('alice')[0].participant
        bob = bob_twitter.opt_in('bob')[0].participant
        alice.set_tip_to(bob, '1.00')
        bob.take_over(alice_twitter, have_confirmation=True)
        self.db.self_check()

    def test_zero_cross_tip_doesnt_become_self_tip(self):
        alice_twitter = self.make_elsewhere('twitter', 1, 'alice')
        bob_twitter   = self.make_elsewhere('twitter', 2, 'bob')
        alice = alice_twitter.opt_in('alice')[0].participant
        bob = bob_twitter.opt_in('bob')[0].participant
        alice.set_tip_to(bob, '1.00')
        alice.set_tip_to(bob, '0.00')
        bob.take_over(alice_twitter, have_confirmation=True)
        self.db.self_check()

    def test_do_not_take_over_zero_tips_giving(self):
        alice_twitter = self.make_elsewhere('twitter', 1, 'alice')
        bob = self.make_elsewhere('twitter', 2, 'bob').opt_in('bob')[0].participant
        carl_twitter  = self.make_elsewhere('twitter', 3, 'carl')
        alice = alice_twitter.opt_in('alice')[0].participant
        carl = carl_twitter.opt_in('carl')[0].participant
        carl.set_tip_to(bob, '1.00')
        carl.set_tip_to(bob, '0.00')
        alice.take_over(carl_twitter, have_confirmation=True)
        ntips = self.db.one("select count(*) from tips")
        assert 2 == ntips
        self.db.self_check()

    def test_do_not_take_over_zero_tips_receiving(self):
        alice_twitter = self.make_elsewhere('twitter', 1, 'alice')
        bob_twitter   = self.make_elsewhere('twitter', 2, 'bob')
        carl_twitter  = self.make_elsewhere('twitter', 3, 'carl')
        alice = alice_twitter.opt_in('alice')[0].participant
        bob = bob_twitter.opt_in('bob')[0].participant
        carl = carl_twitter.opt_in('carl')[0].participant
        bob.set_tip_to(carl, '1.00')
        bob.set_tip_to(carl, '0.00')
        alice.take_over(carl_twitter, have_confirmation=True)
        ntips = self.db.one("select count(*) from tips")
        assert 2 == ntips
        self.db.self_check()

    def test_take_over_fails_if_it_would_result_in_just_a_team_account(self):
        alice_github = self.make_elsewhere('github', 2, 'alice')
        alice = alice_github.opt_in('alice')[0].participant

        a_team_github = self.make_elsewhere('github', 1, 'a_team', is_team=True)
        a_team_github.opt_in('a_team')

        pytest.raises( TeamCantBeOnlyAuth
                     , alice.take_over
                     , a_team_github
                     , have_confirmation=True
                      )

    def test_idempotent(self):
        alice_twitter = self.make_elsewhere('twitter', 1, 'alice')
        bob_github    = self.make_elsewhere('github', 2, 'bob')
        alice = alice_twitter.opt_in('alice')[0].participant
        alice.take_over(bob_github, have_confirmation=True)
        alice.take_over(bob_github, have_confirmation=True)
        self.db.self_check()


class TestParticipant(Harness):
    def setUp(self):
        Harness.setUp(self)
        now = utcnow()
        for username in ['alice', 'bob', 'carl']:
            p = self.make_participant(username, claimed_time=now, elsewhere='twitter')
            setattr(self, username, p)

    def test_bob_is_singular(self):
        expected = True
        actual = self.bob.IS_SINGULAR
        assert actual == expected

    def test_john_is_plural(self):
        expected = True
        self.make_participant('john', number='plural')
        actual = Participant.from_username('john').IS_PLURAL
        assert actual == expected

    def test_can_change_email(self):
        self.alice.update_email('alice@gittip.com')
        expected = 'alice@gittip.com'
        actual = self.alice.email.address
        assert actual == expected

    def test_can_confirm_email(self):
        self.alice.update_email('alice@gittip.com', True)
        actual = self.alice.email.confirmed
        assert actual == True

    def test_cant_take_over_claimed_participant_without_confirmation(self):
        bob_twitter = self.make_elsewhere('twitter', '2', 'bob')
        with self.assertRaises(NeedConfirmation):
            self.alice.take_over(bob_twitter)

    def test_taking_over_yourself_sets_all_to_zero(self):
        bob_twitter = self.make_elsewhere('twitter', '2', 'bob')
        self.alice.set_tip_to(self.bob, '1.00')
        self.alice.take_over(bob_twitter, have_confirmation=True)
        expected = Decimal('0.00')
        actual = self.alice.giving
        assert actual == expected

    def test_alice_ends_up_tipping_bob_two_dollars(self):
        carl_twitter = self.make_elsewhere('twitter', '3', 'carl')
        self.alice.set_tip_to(self.bob, '1.00')
        self.alice.set_tip_to(self.carl, '1.00')
        self.bob.take_over(carl_twitter, have_confirmation=True)
        expected = Decimal('2.00')
        actual = self.alice.get_tip_to('bob')
        assert actual == expected

    def test_bob_ends_up_tipping_alice_two_dollars(self):
        carl_twitter = self.make_elsewhere('twitter', '3', 'carl')
        self.bob.set_tip_to(self.alice, '1.00')
        self.carl.set_tip_to(self.alice, '1.00')
        self.bob.take_over(carl_twitter, have_confirmation=True)
        expected = Decimal('2.00')
        actual = self.bob.get_tip_to('alice')
        assert actual == expected

    def test_ctime_comes_from_the_older_tip(self):
        carl_twitter = self.make_elsewhere('twitter', '3', 'carl')
        self.alice.set_tip_to(self.bob, '1.00')
        self.alice.set_tip_to(self.carl, '1.00')
        self.bob.take_over(carl_twitter, have_confirmation=True)

        tips = self.db.all("SELECT * FROM tips")
        first, second = tips[0], tips[1]

        # sanity checks (these don't count :)
        assert len(tips) == 4
        assert first.tipper, first.tippee == ('alice', 'bob')
        assert second.tipper, second.tippee == ('alice', 'carl')

        expected = first.ctime
        actual = self.db.one("SELECT ctime FROM tips ORDER BY ctime LIMIT 1")
        assert actual == expected

    def test_connecting_unknown_account_fails(self):
        with self.assertRaises(NotSane):
            self.bob.take_over(('github', 'jim'))

    def test_delete_elsewhere_last(self):
        with pytest.raises(LastElsewhere):
            self.alice.delete_elsewhere('twitter', 1)

    def test_delete_elsewhere_last_signin(self):
        self.make_elsewhere('bountysource', self.alice.id, 'alice')
        with pytest.raises(LastElsewhere):
            self.alice.delete_elsewhere('twitter', 1)

    def test_delete_elsewhere_nonsignin(self):
        g = self.make_elsewhere('bountysource', 1, 'alice')
        alice = self.alice
        alice.take_over(g)
        accounts = alice.get_accounts_elsewhere()
        assert accounts['twitter'] and accounts['bountysource']
        alice.delete_elsewhere('bountysource', 1)
        accounts = alice.get_accounts_elsewhere()
        assert accounts['twitter'] and accounts.get('bountysource') is None

    def test_delete_elsewhere_nonexisting(self):
        with pytest.raises(NonexistingElsewhere):
            self.alice.delete_elsewhere('github', 1)

    def test_delete_elsewhere(self):
        g = self.make_elsewhere('github', 1, 'alice')
        alice = self.alice
        alice.take_over(g)
        # test preconditions
        accounts = alice.get_accounts_elsewhere()
        assert accounts['twitter'] and accounts['github']
        # do the thing
        alice.delete_elsewhere('twitter', 1)
        # unit test
        accounts = alice.get_accounts_elsewhere()
        assert accounts.get('twitter') is None and accounts['github']




class Tests(Harness):

    def random_restricted_username(self):
        """helper method to chooses a restricted username for testing """
        from gittip import RESTRICTED_USERNAMES
        random_item = random.choice(RESTRICTED_USERNAMES)
        while random_item.startswith('%'):
            random_item = random.choice(RESTRICTED_USERNAMES)
        return random_item

    def setUp(self):
        Harness.setUp(self)
        self.participant = self.make_participant('user1')  # Our protagonist


    def test_claiming_participant(self):
        now = utcnow()
        self.participant.set_as_claimed()
        actual = self.participant.claimed_time - now
        expected = datetime.timedelta(seconds=0.1)
        assert actual < expected

    def test_changing_username_successfully(self):
        self.participant.change_username('user2')
        actual = Participant.from_username('user2')
        assert self.participant == actual

    def test_changing_username_to_nothing(self):
        with self.assertRaises(UsernameIsEmpty):
            self.participant.change_username('')

    def test_changing_username_to_all_spaces(self):
        with self.assertRaises(UsernameIsEmpty):
            self.participant.change_username('    ')

    def test_changing_username_strips_spaces(self):
        self.participant.change_username('  aaa  ')
        actual = Participant.from_username('aaa')
        assert self.participant == actual

    def test_changing_username_returns_the_new_username(self):
        returned = self.participant.change_username('  foo bar baz  ')
        assert returned == 'foo bar baz', returned

    def test_changing_username_to_too_long(self):
        with self.assertRaises(UsernameTooLong):
            self.participant.change_username('123456789012345678901234567890123')

    def test_changing_username_to_already_taken(self):
        self.make_participant('user2')
        with self.assertRaises(UsernameAlreadyTaken):
            self.participant.change_username('user2')

    def test_changing_username_to_already_taken_is_case_insensitive(self):
        self.make_participant('UsEr2')
        with self.assertRaises(UsernameAlreadyTaken):
            self.participant.change_username('uSeR2')

    def test_changing_username_to_invalid_characters(self):
        with self.assertRaises(UsernameContainsInvalidCharacters):
            self.participant.change_username(u"\u2603") # Snowman

    def test_changing_username_to_restricted_name(self):
        with self.assertRaises(UsernameIsRestricted):
            self.participant.change_username(self.random_restricted_username())

    def test_getting_tips_actually_made(self):
        expected = Decimal('1.00')
        user2 = self.make_participant('user2')
        self.participant.set_tip_to(user2, expected)
        actual = self.participant.get_tip_to('user2')
        assert actual == expected

    def test_getting_tips_not_made(self):
        expected = Decimal('0.00')
        self.make_participant('user2')
        actual = self.participant.get_tip_to('user2')
        assert actual == expected


    # id

    def test_participant_gets_a_long_id(self):
        actual = type(self.make_participant('alice').id)
        assert actual == long


    # number

    def test_cant_go_singular_with_big_tips(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_participant('bob', number='plural')
        carl = self.make_participant('carl')
        carl.set_tip_to(bob, '100.00')
        alice.set_tip_to(bob, '1000.00')
        pytest.raises(HasBigTips, bob.update_number, 'singular')

    def test_can_go_singular_without_big_tips(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_participant('bob', number='plural')
        alice.set_tip_to(bob, '100.00')
        bob.update_number('singular')
        assert Participant.from_username('bob').number == 'singular'

    def test_can_go_plural(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '100.00')
        bob.update_number('plural')
        assert Participant.from_username('bob').number == 'plural'


    # set_tip_to - stt

    def test_stt_sets_tip_to(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '1.00')

        actual = alice.get_tip_to('bob')
        assert actual == Decimal('1.00')

    def test_stt_returns_a_Decimal_and_a_boolean(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_participant('bob')
        actual = alice.set_tip_to(bob, '1.00')
        assert actual == (Decimal('1.00'), True)

    def test_stt_returns_False_for_second_time_tipper(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '1.00')
        actual = alice.set_tip_to(bob, '2.00')
        assert actual == (Decimal('2.00'), False)

    def test_stt_doesnt_allow_self_tipping(self):
        alice = self.make_participant('alice', last_bill_result='')
        self.assertRaises(NoSelfTipping, alice.set_tip_to, 'alice', '10.00')

    def test_stt_doesnt_allow_just_any_ole_amount(self):
        alice = self.make_participant('alice', last_bill_result='')
        self.make_participant('bob')
        self.assertRaises(BadAmount, alice.set_tip_to, 'bob', '1000.00')

    def test_stt_allows_higher_tip_to_plural_receiver(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_participant('bob', number='plural')
        actual = alice.set_tip_to(bob, '1000.00')
        assert actual == (Decimal('1000.00'), True)

    def test_stt_still_caps_tips_to_plural_receivers(self):
        alice = self.make_participant('alice', last_bill_result='')
        self.make_participant('bob', number='plural')
        self.assertRaises(BadAmount, alice.set_tip_to, 'bob', '1000.01')

    def test_stt_fails_to_tip_unknown_people(self):
        alice = self.make_participant('alice', last_bill_result='')
        self.assertRaises(NoTippee, alice.set_tip_to, 'bob', '1.00')


    # giving and receiving

    def test_giving_and_receiving_only_count_latest_tip(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_participant('bob', claimed_time='now')
        alice.set_tip_to(bob, '12.00')
        alice.set_tip_to(bob, '3.00')
        assert alice.giving == Decimal('3.00')
        assert bob.receiving == Decimal('3.00')

    def test_receiving_includes_tips_from_accounts_with_a_working_card(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '3.00')

        expected = Decimal('3.00')
        actual = bob.receiving
        assert actual == expected

    def test_receiving_ignores_tips_from_accounts_with_no_card_on_file(self):
        alice = self.make_participant('alice', last_bill_result=None)
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '3.00')

        expected = Decimal('0.00')
        actual = bob.receiving
        assert actual == expected

    def test_receiving_ignores_tips_from_accounts_with_a_failing_card_on_file(self):
        alice = self.make_participant('alice', last_bill_result="Fail!")
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '3.00')

        expected = Decimal('0.00')
        actual = bob.receiving
        assert actual == expected

    def test_receiving_includes_tips_from_whitelisted_accounts(self):
        alice = self.make_participant( 'alice'
                                     , last_bill_result=''
                                     , is_suspicious=False
                                      )
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '3.00')

        expected = Decimal('3.00')
        actual = bob.receiving
        assert actual == expected

    def test_receiving_includes_tips_from_unreviewed_accounts(self):
        alice = self.make_participant( 'alice'
                                     , last_bill_result=''
                                     , is_suspicious=None
                                      )
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '3.00')

        expected = Decimal('3.00')
        actual = bob.receiving
        assert actual == expected

    def test_receiving_ignores_tips_from_blacklisted_accounts(self):
        alice = self.make_participant( 'alice'
                                     , last_bill_result=''
                                     , is_suspicious=True
                                      )
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '3.00')

        expected = Decimal('0.00')
        actual = bob.receiving
        assert actual == expected

    def test_receiving_includes_taking_when_updated_from_set_tip_to(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_participant('bob', taking=Decimal('42.00'))
        alice.set_tip_to(bob, '3.00')
        assert Participant.from_username('bob').receiving == bob.receiving == Decimal('45.00')


    # pledging

    def test_pledging_only_counts_latest_tip(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_elsewhere('github', 1, 'bob').participant
        alice.set_tip_to(bob, '12.00')
        alice.set_tip_to(bob, '3.00')
        assert alice.pledging == Decimal('3.00')

    def test_pledging_isnt_giving(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_elsewhere('github', 1, 'bob').participant
        alice.set_tip_to(bob, '3.00')
        assert alice.giving == Decimal('0.00')


    # get_number_of_backers - gnob

    def test_gnob_gets_number_of_backers(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_participant('bob', last_bill_result='')
        clancy = self.make_participant('clancy')

        alice.set_tip_to(clancy, '3.00')
        bob.set_tip_to(clancy, '1.00')

        actual = clancy.get_number_of_backers()
        assert actual == 2


    def test_gnob_includes_backers_with_a_working_card_on_file(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '3.00')

        actual = bob.get_number_of_backers()
        assert actual == 1

    def test_gnob_ignores_backers_with_no_card_on_file(self):
        alice = self.make_participant('alice', last_bill_result=None)
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '3.00')

        actual = bob.get_number_of_backers()
        assert actual == 0

    def test_gnob_ignores_backers_with_a_failing_card_on_file(self):
        alice = self.make_participant('alice', last_bill_result="Fail!")
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '3.00')

        actual = bob.get_number_of_backers()
        assert actual == 0


    def test_gnob_includes_whitelisted_backers(self):
        alice = self.make_participant( 'alice'
                                     , last_bill_result=''
                                     , is_suspicious=False
                                      )
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '3.00')

        actual = bob.get_number_of_backers()
        assert actual == 1

    def test_gnob_includes_unreviewed_backers(self):
        alice = self.make_participant( 'alice'
                                     , last_bill_result=''
                                     , is_suspicious=None
                                      )
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '3.00')

        actual = bob.get_number_of_backers()
        assert actual == 1

    def test_gnob_ignores_blacklisted_backers(self):
        alice = self.make_participant( 'alice'
                                     , last_bill_result=''
                                     , is_suspicious=True
                                      )
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '3.00')

        actual = bob.get_number_of_backers()
        assert actual == 0


    def test_gnob_ignores_backers_where_tip_is_zero(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_participant('bob')
        alice.set_tip_to(bob, '0.00')

        actual = bob.get_number_of_backers()
        assert actual == 0

    def test_gnob_looks_at_latest_tip_only(self):
        alice = self.make_participant('alice', last_bill_result='')
        bob = self.make_participant('bob')

        alice.set_tip_to(bob, '1.00')
        alice.set_tip_to(bob, '12.00')
        alice.set_tip_to(bob, '3.00')
        alice.set_tip_to(bob, '6.00')
        alice.set_tip_to(bob, '0.00')

        actual = bob.get_number_of_backers()
        assert actual == 0


    # get_age_in_seconds - gais

    def test_gais_gets_age_in_seconds(self):
        now = utcnow()
        alice = self.make_participant('alice', claimed_time=now)
        actual = alice.get_age_in_seconds()
        assert 0 < actual < 1

    def test_gais_returns_negative_one_if_None(self):
        alice = self.make_participant('alice', claimed_time=None)
        actual = alice.get_age_in_seconds()
        assert actual == -1


    # resolve_unclaimed - ru

    def test_ru_returns_None_for_orphaned_participant(self):
        resolved = self.make_participant('alice').resolve_unclaimed()
        assert resolved is None, resolved

    def test_ru_returns_bitbucket_url_for_stub_from_bitbucket(self):
        unclaimed = self.make_elsewhere('bitbucket', '1234', 'alice')
        stub = Participant.from_username(unclaimed.participant.username)
        actual = stub.resolve_unclaimed()
        assert actual == "/on/bitbucket/alice/"

    def test_ru_returns_github_url_for_stub_from_github(self):
        unclaimed = self.make_elsewhere('github', '1234', 'alice')
        stub = Participant.from_username(unclaimed.participant.username)
        actual = stub.resolve_unclaimed()
        assert actual == "/on/github/alice/"

    def test_ru_returns_twitter_url_for_stub_from_twitter(self):
        unclaimed = self.make_elsewhere('twitter', '1234', 'alice')
        stub = Participant.from_username(unclaimed.participant.username)
        actual = stub.resolve_unclaimed()
        assert actual == "/on/twitter/alice/"

    def test_ru_returns_openstreetmap_url_for_stub_from_openstreetmap(self):
        unclaimed = self.make_elsewhere('openstreetmap', '1', 'alice')
        stub = Participant.from_username(unclaimed.participant.username)
        actual = stub.resolve_unclaimed()
        assert actual == "/on/openstreetmap/alice/"


    # archive

    def test_archive_fails_if_ctr_not_run(self):
        alice = self.make_participant('alice')
        self.make_participant('bob').set_tip_to(alice, Decimal('1.00'))
        with self.db.get_cursor() as cursor:
            pytest.raises(alice.StillReceivingTips, alice.archive, cursor)

    def test_archive_fails_if_balance_is_positive(self):
        alice = self.make_participant('alice', balance=2)
        with self.db.get_cursor() as cursor:
            pytest.raises(alice.BalanceIsNotZero, alice.archive, cursor)

    def test_archive_fails_if_balance_is_negative(self):
        alice = self.make_participant('alice', balance=-2)
        with self.db.get_cursor() as cursor:
            pytest.raises(alice.BalanceIsNotZero, alice.archive, cursor)

    def test_archive_clears_claimed_time(self):
        alice = self.make_participant('alice')
        with self.db.get_cursor() as cursor:
            archived_as = alice.archive(cursor)
        assert Participant.from_username(archived_as).claimed_time is None

    def test_archive_records_an_event(self):
        alice = self.make_participant('alice')
        with self.db.get_cursor() as cursor:
            archived_as = alice.archive(cursor)
        payload = self.db.one("SELECT * FROM events WHERE payload->>'action' = 'archive'").payload
        assert payload['values']['old_username'] == 'alice'
        assert payload['values']['new_username'] == archived_as
