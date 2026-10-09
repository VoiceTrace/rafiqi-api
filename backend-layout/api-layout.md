# Implemented API

The following routes are mounted by app/main.py. /docs, /redoc, /openapi.json and the /media static mount are additional framework surfaces.

| Method | Path | Access | Handler | Service calls |
|---|---|---|---|---|
| POST | `/auth/login` | public; credentials/token in body | `auth.py:login_route` | `auth_svc.login` |
| POST | `/auth/refresh` | public; credentials/token in body | `auth.py:refresh_route` | `auth_svc.refresh_access_token` |
| POST | `/auth/logout` | public; credentials/token in body | `auth.py:logout_route` | `auth_svc.logout` |
| GET | `/study-subjects` | student | `review.py:subjects` | `catalog.list_subjects` |
| GET | `/study-subjects/{subject_id}/chapters` | student | `review.py:chapters` | `catalog.list_chapters` |
| GET | `/study-lessons` | student | `review.py:lessons` | `svc.list_lessons` |
| GET | `/study-lessons/{lesson_id}` | student | `review.py:lesson` | `svc.get_lesson` |
| POST | `/study-sessions` | student | `review.py:create` | `svc.create_or_resume_session` |
| GET | `/study-sessions/by-lesson/{lesson_id}` | student | `review.py:by_lesson` | `svc.get_session_by_lesson` |
| GET | `/study-sessions/{session_id}` | student | `review.py:get_session` | `svc.get_session` |
| GET | `/study-sessions/{session_id}/attempts` | student | `review.py:attempts` | `svc.list_attempts` |
| GET | `/study-mastery` | student | `review.py:mastery` | `svc.list_mastery` |
| POST | `/study-sessions/{session_id}/messages` | student | `review.py:send_message` | `svc.process_message` |
| GET | `/users/me` | authenticated | `users.py:get_me` | `user_svc.get_me` |
| PATCH | `/users/me` | authenticated | `users.py:update_me` | `user_svc.update_me` |
| PUT | `/users/me/avatar` | authenticated | `users.py:upload_own_avatar` | `user_svc.upload_own_avatar` |
| DELETE | `/users/me/avatar` | authenticated | `users.py:remove_own_avatar` | `user_svc.remove_own_avatar` |
| GET | `/users` | teacher | `users.py:list_users` | `user_svc.list_users` |
| POST | `/users` | teacher | `users.py:create_user` | `user_svc.create_user` |
| GET | `/users/{user_id}` | teacher | `users.py:get_user` | `user_svc.get_user` |
| PATCH | `/users/{user_id}` | teacher | `users.py:update_user` | `user_svc.update_user` |
| PUT | `/users/{user_id}/avatar` | teacher | `users.py:upload_user_avatar` | `user_svc.upload_user_avatar` |
| DELETE | `/users/{user_id}/avatar` | teacher | `users.py:remove_user_avatar` | `user_svc.remove_user_avatar` |
| DELETE | `/users/{user_id}` | teacher | `users.py:deactivate_user` | `user_svc.deactivate_user` |
| GET | `/health` | public | `main.py:health` | none; process health only |
