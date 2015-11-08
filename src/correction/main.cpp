
#include <iostream>
#include <cmath>
#include <math.h>
#include "vector_3.h"
#include "correction.h"

using namespace std;

#define X_AXIS 0
#define Y_AXIS 1
#define Z_AXIS 2

#define _USE_MATH_DEFINES
#define delta_diagonal_rod 189.75


float sq(float k)
{
    return k * k;
}


void calculate_delta_tower(float r, float delta_tower[],
                           struct CorrectionData *data)
{
    data->DELTA_DIAGONAL_ROD_2 = delta_diagonal_rod * delta_diagonal_rod;

    // front left tower
    delta_tower[0] = (r + data->tower_adj[3]) * cos((210 + data->tower_adj[0]) * M_PI/180);
    delta_tower[1] = (r + data->tower_adj[3]) * sin((210 + data->tower_adj[0]) * M_PI/180);

    // front right tower
    delta_tower[2] = (r + data->tower_adj[4]) * cos((330 + data->tower_adj[1]) * M_PI/180);
    delta_tower[3] = (r + data->tower_adj[4]) * sin((330 + data->tower_adj[1]) * M_PI/180); 

    // back middle tower
    delta_tower[4] = (r + data->tower_adj[5]) * cos((90 + data->tower_adj[2]) * M_PI/180);
    delta_tower[5] = (r + data->tower_adj[5]) * sin((90 + data->tower_adj[2]) * M_PI/180); 
}


void calculate_cartesian_position(float actuator_mm[], float cartesian_mm[],
                                  float r, struct CorrectionData *data)
{
    float delta_tower[6];

    calculate_delta_tower(r, delta_tower, data);

    Vector3 tower1(delta_tower[0], delta_tower[1], actuator_mm[X_AXIS]);
    Vector3 tower2(delta_tower[2], delta_tower[3], actuator_mm[Y_AXIS]);
    Vector3 tower3(delta_tower[4], delta_tower[5], actuator_mm[Z_AXIS]);

    Vector3 s12 = tower1.sub(tower2);
    Vector3 s23 = tower2.sub(tower3);
    Vector3 s13 = tower1.sub(tower3);

    Vector3 normal = s12.cross(s23);

    float magsq_s12 = s12.magsq();
    float magsq_s23 = s23.magsq();
    float magsq_s13 = s13.magsq();

    float inv_nmag_sq = 1.0F / normal.magsq();
    float q = 0.5F * inv_nmag_sq;

    float a = q * magsq_s23 * s12.dot(s13);

    // negate because we use s12 instead of s21
    float b = q * magsq_s13 * s12.dot(s23) * -1.0F;
    float c = q * magsq_s12 * s13.dot(s23);

    Vector3 circumcenter(
        delta_tower[0] * a + delta_tower[2] * b + delta_tower[4] * c,
        delta_tower[1] * a + delta_tower[3] * b + delta_tower[5] * c,
        actuator_mm[X_AXIS] * a + actuator_mm[Y_AXIS] * b +
          actuator_mm[Z_AXIS] * c);

    float r_sq = 0.5F * q * magsq_s12 * magsq_s23 * magsq_s13;
    //float dist = sqrtf(inv_nmag_sq * (arm_length_squared - r_sq));
    float dist = sqrt(inv_nmag_sq * (data->DELTA_DIAGONAL_ROD_2 - r_sq));

    Vector3 cartesianln = circumcenter.sub(normal.mul(dist));

    cartesian_mm[X_AXIS] = cartesianln[0];
    cartesian_mm[Y_AXIS] = cartesianln[1];
    cartesian_mm[Z_AXIS] = cartesianln[2];
  }


void calculate_delta_position(float cartesian[3], float actuator_mm[], float r,
                              struct CorrectionData *data) 
{
    float delta_tower[6];
    calculate_delta_tower(r, delta_tower, data);

    actuator_mm[0] = sqrt(data->DELTA_DIAGONAL_ROD_2
        - sq(delta_tower[0]-cartesian[0])
        - sq(delta_tower[1]-cartesian[1])) + cartesian[2];

    actuator_mm[1] = sqrt(data->DELTA_DIAGONAL_ROD_2
        - sq(delta_tower[2]-cartesian[0])
        - sq(delta_tower[3]-cartesian[1])) + cartesian[2];

    actuator_mm[2] = sqrt(data->DELTA_DIAGONAL_ROD_2
        - sq(delta_tower[4]-cartesian[0])
        - sq(delta_tower[5]-cartesian[1])) + cartesian[2];
}

void error_simulation(float p0[], float p1[], float error[],
                      struct CorrectionData *data)
{
    float temp[3];
    calculate_delta_position(p0, temp, data->delta_radius, data);
    for (int i = 0; i < 3; i++) temp[i] += error[i];
    calculate_cartesian_position(temp, p1, data->delta_radius + error[3], data);
}

int calculate_error(float p[][3], float err[], int r_en, int h_en,
                    struct CorrectionData *data,
                    struct CorrectionResult *result)
{
    float temp[4][3];
    float error[5] = {0};
    for(int i = 0; i < 4; i++) error_simulation(p[i], temp[i], error, data);
    int flag = 0;
    int count = 0;
    do
    {
        flag = 0;
        for(int i = 0; i < 3; i++)
        {
            float a = temp[i][2] - temp[(i + 1) % 3][2];
            float b = temp[i][2] - temp[(i + 2) % 3][2];

            if(a < -0.001 || b < -0.001)
            {
                error[i] += 0.001;
                for(int i = 0; i < 4; i++) {
                    error_simulation(p[i], temp[i], error, data);
                }
                flag++;
            }
        }


        float c = 0;
        if(r_en) {
            c = temp[3][2] - temp[0][2];
        }

        if(c < -0.001)
        {
            error[3] += 0.001;
            for(int i = 0; i < 4; i++) {
                error_simulation(p[i], temp[i], error, data);
            }
            flag++;
        }
        else if(c > 0.001)
        {
            error[3] -= 0.001;
            for(int i = 0; i < 4; i++) {
                error_simulation(p[i], temp[i], error, data);
            }
            flag++;
        }
        if (count > 25530)
        {
            return 0;
        }
        count++;
    } while (flag);

    if(h_en) {
        error[4] -= temp[3][2];
    }

    for(int i = 0; i < 5; i++) {
        err[i] += error[i];
    }

    float min = err[0];
    for(int i = 1; i < 3; i++)
    {
        if(err[i] < min) min = err[i];
    }

    for(int i = 0; i < 3; i++) err[i] -= min;

    result->X = -1 * err[0];
    result->Y = -1 * err[1];
    result->Z = -1 * err[2];
    result->R = err[3];
    result->H = err[4];

    return 1;
}

int calculator(float init_endstop_x, float init_endstop_y, float init_endstop_z,
               float init_endstop_h, float input_x, float input_y,
               float input_z, float input_h, float delta_radious,
               struct CorrectionResult *result) {
    struct CorrectionData data = {
        {0, 0, 0},
        96.7,
        0,
        {0, 0, 0, 0, 0, 0},
        {0, 0, 0}
    };

    data.endstop_adj[0] = init_endstop_x;  // initial M666 X value
    data.endstop_adj[1] = init_endstop_y;  // initial M666 Y value
    data.endstop_adj[2] = init_endstop_z;  // initial M666 Z value
    data.max_pos[Z_AXIS] = init_endstop_h;  // initial M666 H value
    data.delta_radius = delta_radious;  // initial M666 R value

    bool r_en = false; // enable R modification
    bool h_en = true; // enable H modification

    // 4 or 3 points input. If r_en == false && h_en == false, only 3 points
    // needed.
    float p[4][3] =
    {
       {-73.61 , -42.50 , input_x},
       {73.61 , -42.50 , input_y},
       {0.00 , 85.00 , input_z},
       {0.00 , 0.00 , input_h}   // 4th point should near the center
    };

    float error[5];
    for (int i = 0; i < 3; i++) error[i] = -1 * data.endstop_adj[i];
    error[3] = data.delta_radius;
    error[4] = data.max_pos[Z_AXIS];

    if(calculate_error(p, error, r_en, h_en, &data, result))
    {
        for (int i = 0; i < 3; i++) {
            data.endstop_adj[i] = -1 * error[i];
        }
        if (r_en) data.delta_radius = error[3];
        if (h_en) data.max_pos[Z_AXIS] = error[4];

        return 0;
    } else {
        return 1;
    }
}


int main()
{
    struct CorrectionResult result;
    calculator(
        0, 0, 0, 242,  // init endstops
       -0.4374, -0.7375, -0.6312, 0,    // input values
        96.7, &result);

    cout << "M666X" << result.X << "Y" << result.Y << "Z" <<  result.Z << "R"
         << result.R << "H" << result.H << endl;

    return 0;
}

