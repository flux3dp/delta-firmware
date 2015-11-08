//copy from smoothie //aven_0812

#ifndef _VECTOR3_H
#define _VECTOR3_H

class Vector3
{
public:
    Vector3();
    Vector3(float, float, float);

    float&   operator[](int);

    Vector3  cross(const Vector3);

    float    dot(const Vector3);

    float    magsq();
    float    mag();

    Vector3  add(const Vector3);
    Vector3  sub(const Vector3);

    Vector3  mul(float);

    Vector3  unit(void);

private:
    float  elem[3];
    static float nan;
};

// typedef float Vector3[3];

// float* cross_product(Vector3 vec1, Vector3 vec2, Vector3 out);
// float dot_product(Vector3 vec1, Vector3 vec2);
// float magsq(Vector3 vec);
// float* vecsub(Vector3 vec1, Vector3 vec2, Vector3 out)
// float* scalar_mul(Vector3 vec, float scalar, Vector3 out)

#endif /* _VECTOR3_H */









#if 0
/*
  vector_3.cpp - Vector library for bed leveling
  Copyright (c) 2012 Lars Brubaker.  All right reserved.

  This library is free software; you can redistribute it and/or
  modify it under the terms of the GNU Lesser General Public
  License as published by the Free Software Foundation; either
  version 2.1 of the License, or (at your option) any later version.

  This library is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
  Lesser General Public License for more details.

  You should have received a copy of the GNU Lesser General Public
  License along with this library; if not, write to the Free Software
  Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
*/
#ifndef VECTOR_3_H
#define VECTOR_3_H

//#ifdef ENABLE_AUTO_BED_LEVELING
class matrix_3x3;

struct vector_3
{
	float x, y, z;

        vector_3();
	vector_3(float x, float y, float z);

	static vector_3 cross(vector_3 a, vector_3 b);

	vector_3 operator+(vector_3 v);
	vector_3 operator-(vector_3 v);
	void normalize();
	float get_length();
	vector_3 get_normal();

	void debug(const char title[]);
	
	void apply_rotation(matrix_3x3 matrix);
};

struct matrix_3x3
{
	float matrix[9];

	static matrix_3x3 create_from_rows(vector_3 row_0, vector_3 row_1, vector_3 row_2);
	static matrix_3x3 create_look_at(vector_3 target);
	static matrix_3x3 transpose(matrix_3x3 original);

	void set_to_identity();

	void debug(const char title[]);
};


void apply_rotation_xyz(matrix_3x3 rotationMatrix, float &x, float& y, float& z);
//#endif // ENABLE_AUTO_BED_LEVELING

#endif // VECTOR_3_H
#endif
