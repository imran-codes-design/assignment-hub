from django.test import Client, TestCase
from django.urls import resolve, reverse

from .models import User


class RegistrationRoleSecurityTests(TestCase):
    def registration_data(self, username, **extra):
        data = {
            "username": username,
            "first_name": "Test",
            "last_name": "Account",
            "email": f"{username}@example.com",
            "password1": "Secure-Test-Password-934!",
            "password2": "Secure-Test-Password-934!",
        }
        data.update(extra)
        return data

    def test_public_registration_cannot_create_writer_account(self):
        response = self.client.post(
            reverse("register"),
            self.registration_data("newclient", role="writer"),
        )

        self.assertRedirects(response, reverse("login"))
        user = User.objects.get(username="newclient")
        self.assertEqual(user.role, "client")

    def test_forged_admin_role_is_ignored(self):
        response = self.client.post(
            reverse("register"),
            self.registration_data("forgedadmin", role="admin"),
        )

        self.assertRedirects(response, reverse("login"))
        user = User.objects.get(username="forgedadmin")
        self.assertEqual(user.role, "client")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_registration_without_role_creates_normal_client(self):
        response = self.client.post(
            reverse("register"),
            self.registration_data("normalclient"),
        )

        self.assertRedirects(response, reverse("login"))
        user = User.objects.get(username="normalclient")
        self.assertEqual(user.role, "client")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_registration_form_does_not_expose_role_choice(self):
        response = self.client.get(reverse("register"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="role"')


class AccountPagePresentationTests(TestCase):
    def test_login_page_renders_existing_fields_and_csrf_form(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')
        self.assertContains(response, 'method="post"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, reverse("register"))
        self.assertContains(response, reverse("home"))

    def test_login_submission_still_authenticates_existing_user(self):
        User.objects.create_user(
            username="login-ui-user",
            password="Secure-Test-Password-934!",
            role="client",
        )

        response = self.client.post(
            reverse("login"),
            {
                "username": "login-ui-user",
                "password": "Secure-Test-Password-934!",
            },
        )

        self.assertRedirects(
            response,
            reverse("client_dashboard"),
            fetch_redirect_response=False,
        )
        self.assertIn("_auth_user_id", self.client.session)

    def test_register_page_renders_existing_fields_without_role_selector(self):
        response = self.client.get(reverse("register"))

        self.assertEqual(response.status_code, 200)
        for field_name in (
            "username",
            "first_name",
            "last_name",
            "email",
            "password1",
            "password2",
        ):
            with self.subTest(field=field_name):
                self.assertContains(response, f'name="{field_name}"')
        self.assertNotContains(response, 'name="role"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, reverse("login"))
        self.assertContains(response, reverse("home"))

    def test_register_page_displays_field_validation_errors(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "invalid-register-ui",
                "first_name": "",
                "last_name": "",
                "email": "not-an-email",
                "password1": "short",
                "password2": "different",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter a valid email address.")
        self.assertContains(response, "The two password fields didn’t match.")


class HomeRoutingAndLogoutTests(TestCase):
    def create_user(self, username, role, is_staff=False):
        return User.objects.create_user(
            username=username,
            password="test-password",
            role=role,
            is_staff=is_staff,
        )

    def test_named_home_url_resolves_to_root(self):
        self.assertEqual(reverse("home"), "/")
        self.assertEqual(resolve("/").url_name, "home")

    def test_anonymous_root_returns_public_landing_page(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/public_home.html")
        self.assertContains(response, "Academic support, shaped around")
        self.assertContains(response, "your brief.")

    def test_public_landing_page_lists_all_services(self):
        response = self.client.get(reverse("home"))

        for service in (
            "Assignment Support",
            "Dissertation Support",
            "Research Support",
            "Programming &amp; University Projects",
            "AI &amp; Data Science",
            "Data Analysis",
        ):
            with self.subTest(service=service):
                self.assertContains(response, service)

    def test_public_landing_page_links_to_login_and_registration(self):
        response = self.client.get(reverse("home"))

        self.assertContains(response, f'href="{reverse("login")}"')
        self.assertContains(response, f'href="{reverse("register")}"')

    def test_client_is_routed_to_client_dashboard(self):
        user = self.create_user("client-home", "client")
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertRedirects(response, reverse("client_dashboard"))

    def test_writer_is_routed_to_writer_dashboard(self):
        user = self.create_user("writer-home", "writer")
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertRedirects(response, reverse("writer_dashboard"))

    def test_staff_is_routed_to_admin_dashboard(self):
        user = self.create_user("staff-home", "client", is_staff=True)
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertRedirects(response, reverse("admin_dashboard"))

    def test_unexpected_role_receives_forbidden_response(self):
        user = self.create_user("invalid-role", "unexpected")
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 403)

    def test_get_logout_does_not_log_user_out(self):
        user = self.create_user("get-logout", "client")
        self.client.force_login(user)

        response = self.client.get(reverse("logout"))

        self.assertEqual(response.status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

    def test_post_logout_logs_user_out(self):
        user = self.create_user("post-logout", "client")
        self.client.force_login(user)

        response = self.client.post(reverse("logout"))

        self.assertRedirects(response, reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_post_logout_requires_csrf_token(self):
        user = self.create_user("csrf-logout", "client")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)

        response = csrf_client.post(reverse("logout"))

        self.assertEqual(response.status_code, 403)
        self.assertIn("_auth_user_id", csrf_client.session)

    def test_post_logout_succeeds_with_csrf_token(self):
        user = self.create_user("csrf-valid-logout", "client")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)
        csrf_response = csrf_client.get(reverse("login"))
        token = csrf_response.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("logout"),
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", csrf_client.session)
