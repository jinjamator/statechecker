import {Injectable} from '@angular/core';
import {CanActivate, Router} from '@angular/router';
import {Observable, of} from 'rxjs';
import {catchError, map} from 'rxjs/operators';
import {environment} from "../../environments/environment";
import {BackendService} from "./backend.service";

@Injectable()
export class AuthGuardService implements CanActivate {

  constructor(public router: Router, private backendService: BackendService) {
  }

  canActivate(): Observable<boolean> | boolean {
    if (!environment.login_required || localStorage.getItem('isLoggedIn') == 'true') {
      return true;
    }
    // Not signed in through the login form - but a session may exist anyway:
    // the Synaptic portal's single sign-on starts one before this page loads.
    // Ask the server before sending anyone to the login form.
    return this.backendService.getSession().pipe(
      map((s) => {
        localStorage.setItem('isLoggedIn', 'true');
        localStorage.setItem('userName', s['username']);
        localStorage.setItem('userRole', String(s['role']));
        return true;
      }),
      catchError(() => {
        this.router.navigate(['login']);
        return of(false);
      })
    );
  }
}
