export const MIN_SIGNUP_PASSWORD_LENGTH = 12;
export const MAX_SIGNUP_PASSWORD_LENGTH = 128;

export class AuthInputError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthInputError";
  }
}

export function validateSignupPassword(password: string) {
  if (password.length < MIN_SIGNUP_PASSWORD_LENGTH) {
    throw new AuthInputError(`Passordet må ha minst ${MIN_SIGNUP_PASSWORD_LENGTH} tegn.`);
  }
  if (password.length > MAX_SIGNUP_PASSWORD_LENGTH) {
    throw new AuthInputError(`Passordet kan ha maksimalt ${MAX_SIGNUP_PASSWORD_LENGTH} tegn.`);
  }
  return password;
}
